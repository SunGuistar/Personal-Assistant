"""确定性总结流水线：切分 → map → reduce → final，仿 wechat-chat-summary 的方法论。

与 Agent 自由问答的区别：本模块的流程由代码写死，不依赖模型自觉——
- 切分确定性：每条消息恰好进入一个 chunk，无截断；
- map：每个 chunk 一次结构化调用，输出 JSON（话题/要点/原话）；
- reduce：fan-in 逐级合并，直到规模可直接进 final；
- final：按固定 Schema 生成报告，统计数字全部来自本地计算，杜绝编造。

数据来自归一化库（只读），报告写入 Output/ 目录。
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from env_bootstrap import load_hub_env

load_hub_env()  # 独立运行时也能读到 DASHSCOPE_API_KEY（权威源在用户目录，见 env_bootstrap）

from ..structured.structured_message import StructuredMessage, from_raw_rows, to_llm_text  # noqa: E402

DEFAULT_DB_PATH = ROOT_DIR / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"
OUTPUT_ROOT = ROOT_DIR / "Output"

# 切分参数（与 wechat-chat-summary 对齐，见 AGENTS.md/settings 注释）
CHUNK_MAX_MESSAGES = 500
CHUNK_MAX_CHARS = 24000
CHUNK_MAX_MINUTES = 240
HARD_GAP_MINUTES = 90
# reduce 每轮合并的份数
REDUCE_FAN_IN = 4
# 超过该 chunk 数才启用 reduce，否则 map 结果直接进 final
REDUCE_THRESHOLD = 5

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


# ---------------------------------------------------------------- 数据读取

def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise RuntimeError(f"找不到归一化聊天库 {db_path}，请先运行 normalize_snapshot.py。")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_day_messages(
    db_path: Path, date: str, chat_id: str | None = None
) -> tuple[str, list[StructuredMessage]]:
    """读取指定日期的全部消息。

    chat_id 显式给出时按该群过滤；未给出且库中恰有一个群时取该群
    （与历史单群行为一致）；多群且未指定时报错（阶段 3.5 多群适配）。
    """

    day = datetime.strptime(date.strip(), "%Y-%m-%d")
    start_ts = int(day.replace(hour=0, minute=0, second=0).timestamp())
    end_ts = int(day.replace(hour=23, minute=59, second=59).timestamp())
    with _connect(db_path) as connection:
        chats = connection.execute(
            "SELECT chat_id, display_name FROM chats"
        ).fetchall()
        if chat_id:
            match = [row for row in chats if str(row["chat_id"]) == chat_id]
            if not match:
                raise RuntimeError(f"聊天库中找不到群: {chat_id}（先用 list_chats 查询）")
            chat_row = match[0]
        elif len(chats) == 1:
            chat_row = chats[0]
        else:
            raise RuntimeError(
                f"库里存在 {len(chats)} 个群，请通过 chat_id 指定要总结的群（先用 list_chats 查询）。"
            )
        chat_id = str(chat_row["chat_id"])
        chat_name = str(chat_row["display_name"])
        rows = connection.execute(
            """SELECT message_id, chat_id, timestamp, time, sender, text, msg_type, render_type
               FROM messages WHERE chat_id = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp, message_id""",
            (chat_id, start_ts, end_ts),
        ).fetchall()
    if not rows:
        raise RuntimeError(f"{date} 没有消息记录。")
    raw_rows = [
        {
            "id": row["message_id"],
            "createTime": row["timestamp"],
            "senderDisplayName": row["sender"],
            "renderType": row["render_type"],
            "content": row["text"],
        }
        for row in rows
    ]
    # from_raw_rows 只做去重和排序，字段已在库中归一化过
    messages = from_raw_rows(chat_id, raw_rows)
    return chat_name, messages


# ---------------------------------------------------------------- 确定性切分

def build_chunks(messages: list[StructuredMessage]) -> list[list[StructuredMessage]]:
    """按条数/字符/时长/硬间隔切分。每个 chunk 是连续消息，无遗漏、无重叠。"""

    chunks: list[list[StructuredMessage]] = []
    current: list[StructuredMessage] = []
    current_chars = 0
    for message in messages:
        if current:
            first_ts = current[0].timestamp
            gap_minutes = (message.timestamp - current[-1].timestamp) / 60
            span_minutes = (message.timestamp - first_ts) / 60
            if (
                len(current) >= CHUNK_MAX_MESSAGES
                or current_chars + len(message.text) > CHUNK_MAX_CHARS
                or span_minutes > CHUNK_MAX_MINUTES
                or gap_minutes > HARD_GAP_MINUTES
            ):
                chunks.append(current)
                current, current_chars = [], 0
        current.append(message)
        current_chars += len(message.text)
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- LLM 调用

def _build_llm():
    # 模型/key/endpoint 统一由 llm_config 提供；流水线只需覆盖输出上限
    from ..llm_config import build_llm

    return build_llm(max_tokens=8192)


def _extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取第一个完整 JSON 对象（容忍 markdown 代码块包裹）。"""

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError(f"模型输出中没有 JSON: {text[:200]}")
    depth = 0
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : index + 1])
    raise ValueError(f"模型输出的 JSON 不完整: {text[:200]}")


def _chat_json(llm, system: str, user: str) -> dict[str, Any]:
    """调用模型并提取 JSON；按模型特性附加 JSON mode 参数（如 qwen3.5 关闭思考模式）。"""

    from ..llm_config import get_json_mode_kwargs

    response = llm.invoke(
        [("system", system), ("human", user)],
        response_format={"type": "json_object"},
        **get_json_mode_kwargs(llm),
    )
    return _extract_json(response.content)


# ---------------------------------------------------------------- 三阶段

MAP_SYSTEM = """你是微信群聊分析助手。把给定时段的聊天记录提炼为结构化 JSON。
只输出 JSON，不要其他文字。JSON 结构：
{"summary": "该时段一两句概述",
 "topics": [{"title": "话题标题（短句）",
             "key_points": ["要点1", "要点2"],
             "quotes": [{"sender": "发言人", "time": "MM-DD HH:MM", "text": "原话摘录"}]}]}
要求：话题按重要度排序，最多 5 个；每个话题要点 2-4 条；quotes 从原文挑选有代表性的原话，每个话题最多 2 条，必须原文照抄、不得改写。"""

REDUCE_SYSTEM = """你是微信群聊分析助手。把多个时段的分析结果合并成一份，去掉重复话题、保留各话题的时间范围。
只输出 JSON，不要其他文字。JSON 结构：
{"summary": "合并后的一两句概述",
 "topics": [{"title": "话题标题",
             "time_ranges": ["MM-DD HH:MM-HH:MM"],
             "key_points": ["要点"],
             "quotes": [{"sender": "发言人", "time": "MM-DD HH:MM", "text": "原话"}]}]}
要求：同一事件/话题只保留一条，time_ranges 可含多个区间；quotes 每个话题最多保留 2 条最有代表性的。"""

FINAL_SYSTEM = """你是微信群日报撰写助手。基于各时段的合并分析结果和本地统计，撰写最终日报。
只输出 JSON，不要其他文字。JSON 结构：
{"summary": "今日总览：一段话概括全天",
 "highlights": ["今日速览要点1", "要点2", "要点3"],
 "topics": [{"title": "话题标题",
             "time_ranges": ["MM-DD HH:MM-HH:MM"],
             "discussion": "该话题的讨论脉络，2-4 个短段，用\\n分隔",
             "quotes": [{"sender": "发言人", "time": "MM-DD HH:MM", "text": "原话"}]}],
 "observations": ["AI 观察1", "观察2"],
 "closing": "报告结尾：一段话收束，可含展望"}
要求：topics 最多 6 个，按时间或重要度排序；discussion 只基于输入材料，不得引入外部信息；quotes 必须来自输入。"""


def _map_chunk(llm, chat_name: str, chunk: list[StructuredMessage]) -> dict[str, Any]:
    first, last = chunk[0], chunk[-1]
    user = (
        f"群名：{chat_name}\n"
        f"时段：{first.time} ~ {last.time}（共 {len(chunk)} 条消息）\n\n"
        f"聊天记录：\n{to_llm_text(chunk)}"
    )
    return _chat_json(llm, MAP_SYSTEM, user)


def _reduce_once(llm, items: list[dict[str, Any]]) -> dict[str, Any]:
    user = f"共 {len(items)} 份时段分析，请合并：\n{json.dumps(items, ensure_ascii=False)}"
    return _chat_json(llm, REDUCE_SYSTEM, user)


def _local_stats(messages: list[StructuredMessage]) -> dict[str, Any]:
    """本地统计：报告里的数字必须来自这里，不让模型生成数字。"""

    senders: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for message in messages:
        senders[message.sender] = senders.get(message.sender, 0) + 1
        type_counts[message.msg_type] = type_counts.get(message.msg_type, 0) + 1
    top = sorted(senders.items(), key=lambda item: item[1], reverse=True)[:10]
    return {
        "message_count": len(messages),
        "participant_count": len(senders),
        "type_counts": type_counts,
        "top_senders": [{"sender": name, "count": count} for name, count in top],
    }


def run_pipeline(
    chat_name: str,
    messages: list[StructuredMessage],
    progress_cb: Any = None,
) -> dict[str, Any]:
    """执行 map/reduce/final，返回报告数据字典。

    progress_cb：可选进度回调（0-100 整数）；默认 None 行为与历史版本一致。
    """

    llm = _build_llm()
    chunks = build_chunks(messages)
    print(f"[summarizer] 切分为 {len(chunks)} 个 chunk")

    def emit_progress(value: int) -> None:
        if progress_cb is not None:
            progress_cb(value)

    emit_progress(5)

    # map：4 路并发，每个 chunk 独立结构化分析
    done_count = 0

    def map_one(chunk):
        nonlocal done_count
        result = _map_chunk(llm, chat_name, chunk)
        done_count += 1
        emit_progress(5 + int(done_count / max(len(chunks), 1) * 80))
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        map_results = list(executor.map(map_one, chunks))
    print(f"[summarizer] map 完成：{len(map_results)} 份时段分析")

    # reduce：份数过多时逐级合并；不超过阈值则跳过直接进 final
    current = map_results
    round_index = 1
    while len(current) > REDUCE_THRESHOLD:
        groups = [current[i : i + REDUCE_FAN_IN] for i in range(0, len(current), REDUCE_FAN_IN)]
        current = [_reduce_once(llm, group) for group in groups]
        print(f"[summarizer] reduce 第 {round_index} 轮：{len(groups)} 份 → {len(current)} 份")
        round_index += 1

    stats = _local_stats(messages)
    user = (
        f"群名：{chat_name}\n"
        f"本地统计（权威数据，直接引用）：{json.dumps(stats, ensure_ascii=False)}\n\n"
        f"各时段合并分析：\n{json.dumps(current, ensure_ascii=False)}"
    )
    report = _final_with_retry(llm, user)
    report["chat_name"] = chat_name
    report["date"] = datetime.fromtimestamp(messages[0].timestamp).strftime("%Y-%m-%d")
    report["activity"] = stats
    emit_progress(95)
    print("[summarizer] final 完成")
    return report


def _final_with_retry(llm, user: str, max_attempts: int = 2) -> dict[str, Any]:
    """final 阶段带重试。

    长输入 + JSON mode 下模型偶发退化（复读垃圾 token 到输出上限、输出非 JSON），
    实测同输入成功率约 2/3，重试一次可将成功率提升到约 8-9 成。
    仅重试 final，map/reduce 不重试。
    """

    from openai import LengthFinishReasonError

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return _chat_json(llm, FINAL_SYSTEM, user)
        except (ValueError, LengthFinishReasonError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                print(f"[summarizer] final 第 {attempt} 次失败（{type(exc).__name__}），重试")
    raise last_exc


# ---------------------------------------------------------------- 入口

def run_summary(
    date: str,
    db_path: Path = DEFAULT_DB_PATH,
    chat_id: str | None = None,
    progress_cb: Any = None,
) -> dict[str, str]:
    """跑完整流水线并渲染落盘，返回 {'html': ..., 'png': ...}。

    chat_id 指定群（多群必传）；不传且单群时行为与历史版本一致。
    progress_cb 为可选进度回调，透传给流水线。
    """

    from ..normal_tools.report_render import export_png, render_html

    chat_name, messages = load_day_messages(db_path, date, chat_id=chat_id)
    report = run_pipeline(chat_name, messages, progress_cb=progress_cb)

    # 输出目录：Output/<群名>/YYYY-MM-DD群聊总结_YYYYMMDDHHMM.html(.png)
    # 文件名带生成时间戳，用于区分同一日期多次生成的报告
    safe_name = INVALID_FILENAME_CHARS.sub("_", chat_name).strip() or "未知群聊"
    out_dir = OUTPUT_ROOT / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M")
    html_path = out_dir / f"{report['date']}_群聊总结_{stamp}.html"
    png_path = out_dir / f"{report['date']}_群聊总结_{stamp}.png"

    html_text = render_html(report)
    html_path.write_text(html_text, encoding="utf-8")

    png_result = export_png(html_path, png_path)
    return {
        "html": str(html_path),
        "png": str(png_path) if png_result else "",
        "png_note": "" if png_result else "PNG 未生成（需安装 playwright 和浏览器内核）",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python summarizer.py YYYY-MM-DD")
    paths = run_summary(sys.argv[1])
    print("HTML:", paths["html"])
    print("PNG :", paths["png"] or paths["png_note"])
