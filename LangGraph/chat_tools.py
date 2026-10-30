"""只读工具集：供 LangGraph Agent 查询归一化聊天库。

主要功能与对应函数：
- list_chats()      列出库里的群和消息总数（Agent 每次任务的第一步）
- get_stats(date)   按天统计：消息总数、类型分布、发言排行 Top10（先摸底再细读）
- get_messages(date, start_hour, end_hour, limit)
                    按天+小时段取消息原文，返回 "[MM-DD HH:MM] 发送者: 正文"
                    格式文本；单次硬上限 1000 条，强制 Agent 分时段多次调用
- search_messages(keyword, date, limit)
                    关键词搜索消息正文，适合"谁说了某话题"类精准定位

公共辅助（不直接暴露为工具）：
- _db_path()        解析库路径：环境变量 WECHAT_AGENT_DB 优先，默认
                    GetWechatInfo/DataInfo/chat_snapshot_normalized.sqlite3
- _connect()        打开连接：mode=ro 物理只读，误写 SQL 直接报错
- _day_range()      把 YYYY-MM-DD 转成当天 [00:00:00, 23:59:59] 的时间戳闭区间
- _rows_to_lines()  把查询结果行格式化为 LLM 可读的聊天记录文本
- ALL_TOOLS         工具注册表：新工具写好 @tool 函数后挂进此列表即可被 Agent 发现

所有工具只读（sqlite3 以 mode=ro 打开），不提供任何修改/导出能力。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

# 注意：@tool 函数的 docstring 和参数签名会被 LangGraph 直接暴露给 LLM，
# 作为模型判断"何时调用本工具、传什么参数"的依据。改动 docstring = 改变模型行为。
DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent
    / "GetWechatInfo" / "DataInfo" / "chat_snapshot_normalized.sqlite3"
)


def _db_path() -> Path:
    # 环境变量优先；未配置时回落到归一化库固定位置
    configured = os.environ.get("WECHAT_AGENT_DB", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.exists():
        raise RuntimeError(f"找不到归一化聊天库 {path}，请先运行 normalize_snapshot.py。")
    # mode=ro：SQLite 层面的物理只读。即使工具代码里误写 INSERT/UPDATE 也会直接报错，
    # 从机制上保证 Agent"只分析不修改"，而不只是靠约定。
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _day_range(date: str) -> tuple[int, int]:
    day = datetime.strptime(date.strip(), "%Y-%m-%d")
    start = int(day.replace(hour=0, minute=0, second=0).timestamp())
    end = int(day.replace(hour=23, minute=59, second=59).timestamp())
    return start, end


def _rows_to_lines(rows: list[sqlite3.Row]) -> str:
    return "\n".join(f"[{row['time']}] {row['sender']}: {row['text']}" for row in rows)


@tool
def list_chats() -> str:
    """列出聊天库里有哪些群以及消息总数。回答任何问题前先用它确认有哪些数据。"""

    with _connect() as connection:
        rows = connection.execute(
            "SELECT chat_id, display_name FROM chats ORDER BY display_name"
        ).fetchall()
        counts = {
            row["chat_id"]: row["n"]
            for row in connection.execute(
                "SELECT chat_id, count(*) AS n FROM messages GROUP BY chat_id"
            )
        }
    if not rows:
        return "聊天库为空。"
    return "\n".join(
        f"{row['display_name']} ({row['chat_id']}): {counts.get(row['chat_id'], 0)} 条消息"
        for row in rows
    )


@tool
def get_stats(date: str) -> str:
    """获取指定日期这一天的聊天概况统计（总消息数、各类型数量、发言最多的成员）。

    Args:
        date: 日期，格式 YYYY-MM-DD，例如 2026-10-27。
    """

    start, end = _day_range(date)
    with _connect() as connection:
        total = connection.execute(
            "SELECT count(*) FROM messages WHERE timestamp >= ? AND timestamp <= ?",
            (start, end),
        ).fetchone()[0]
        by_type = connection.execute(
            """SELECT msg_type, count(*) AS n FROM messages
               WHERE timestamp >= ? AND timestamp <= ? GROUP BY msg_type ORDER BY n DESC""",
            (start, end),
        ).fetchall()
        by_sender = connection.execute(
            # 排除"系统"类型（进出群提示、群公告等），否则发言排行会被非真人条目污染
            """SELECT sender, count(*) AS n FROM messages
               WHERE timestamp >= ? AND timestamp <= ? AND msg_type != '系统'
               GROUP BY sender ORDER BY n DESC LIMIT 10""",
            (start, end),
        ).fetchall()
    if not total:
        return f"{date} 没有消息记录。"
    lines = [f"{date} 共 {total} 条消息。"]
    lines.append("类型分布: " + "、".join(f"{row['msg_type']} {row['n']}" for row in by_type))
    lines.append(
        "发言排行: " + "、".join(f"{row['sender']}({row['n']})" for row in by_sender)
    )
    return "\n".join(lines)


@tool
def get_messages(date: str, start_hour: int = 0, end_hour: int = 23, limit: int = 500) -> str:
    """按日期和小时段读取消息原文，返回格式化聊天记录（每行 '[MM-DD HH:MM] 发送者: 正文'）。
    一天消息量很大时必须分多次调用本工具（每次只取几个小时），不要试图一次读全天。

    Args:
        date: 日期，格式 YYYY-MM-DD。
        start_hour: 开始小时（含），0-23，默认 0。
        end_hour: 结束小时（含），0-23，默认 23。
        limit: 最多返回条数，默认 500，最大 1000。
    """

    day = datetime.strptime(date.strip(), "%Y-%m-%d")
    start = int(day.replace(hour=max(0, min(23, start_hour)), minute=0, second=0).timestamp())
    end = int(day.replace(hour=max(0, min(23, end_hour)), minute=59, second=59).timestamp())
    limit = max(1, min(int(limit), 1000))
    # 硬上限 1000 条：工具的返回值整体进入 LLM 上下文，限制它就是控制 token 成本、
    # 防止单日数千条消息一次性塞爆上下文——这是"精简"策略在代码上的落点。
    with _connect() as connection:
        rows = connection.execute(
            """SELECT time, sender, text FROM messages
               WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp LIMIT ?""",
            (start, end, limit),
        ).fetchall()
    if not rows:
        return f"{date} {start_hour}:00-{end_hour}:59 没有消息。"
    return f"{date} {start_hour}:00-{end_hour}:59 共 {len(rows)} 条：\n" + _rows_to_lines(rows)


@tool
def search_messages(keyword: str, date: str = "", limit: int = 30) -> str:
    """按关键词搜索消息正文，返回匹配的聊天记录。适合回答"谁说了某话题"类问题。

    Args:
        keyword: 要搜索的关键词。
        date: 可选，限定日期 YYYY-MM-DD；留空搜索全部日期。
        limit: 最多返回条数，默认 30。
    """

    keyword = str(keyword or "").strip()
    if not keyword:
        return "关键词不能为空。"
    like = f"%{keyword}%"
    limit = max(1, min(int(limit), 100))
    clauses = "text LIKE ?"
    params: list = [like]
    if date.strip():
        start, end = _day_range(date)
        clauses += " AND timestamp >= ? AND timestamp <= ?"
        params += [start, end]
    params.append(limit)
    with _connect() as connection:
        rows = connection.execute(
            f"""SELECT time, sender, text FROM messages
                WHERE {clauses} ORDER BY timestamp LIMIT ?""",
            params,
        ).fetchall()
    if not rows:
        return f"没有找到包含 {keyword!r} 的消息。"
    return f"找到 {len(rows)} 条包含 {keyword!r} 的消息：\n" + _rows_to_lines(rows)


@tool
def summarize_chat(date: str) -> str:
    """生成指定日期的群聊总结报告（仿日报版式的 HTML，可选 PNG），返回报告文件路径。
    用户要求"总结/日报/回顾"某天聊天时必须使用本工具——内部是确定性 map/reduce 流水线，
    覆盖率与格式有保证；不要改用 get_messages 自己逐片翻消息。

    Args:
        date: 日期，格式 YYYY-MM-DD，例如 2026-10-27。
    """

    # 延迟导入：普通问答不触发流水线的依赖加载
    import sys
    from pathlib import Path as _Path

    script_dir = _Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from summarizer import run_summary

    # openai 错误（dashscope 走 OpenAI 兼容模式，额度/限流/网络问题都以这些异常抛出）
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        PermissionDeniedError,
        RateLimitError,
    )

    try:
        paths = run_summary(date.strip())
    except (RuntimeError, ValueError) as exc:
        return f"生成报告失败: {exc}"
    except PermissionDeniedError:
        # 典型场景：DashScope 免费额度耗尽（403 Free quota exhausted）。
        # 不把原始报错抛给上层，转成人话提示，Agent 可继续对话。
        return (
            "生成报告失败：模型 API 额度已用完（403）。"
            "请到阿里云百炼控制台充值或关闭\"仅使用免费额度\"后重试。"
        )
    except RateLimitError:
        return "生成报告失败：模型 API 限流中，请稍等片刻后重试。"
    except (APIConnectionError, APITimeoutError):
        return "生成报告失败：模型 API 网络连接失败，请检查网络后重试。"
    except APIError as exc:
        return f"生成报告失败：模型 API 返回错误（HTTP {getattr(exc, 'status_code', '?')}），请稍后重试。"
    lines = [f"报告已生成（{date}）：", f"  HTML: {paths['html']}"]
    lines.append(f"  PNG : {paths['png']}" if paths["png"] else f"  PNG : 未生成（{paths['png_note']}）")
    lines.append("请向用户告知文件位置，并基于报告内容给出 3-5 句话的简要概括。")
    return "\n".join(lines)


# 解耦点：新增工具只需在本文件里写一个 @tool 函数，再挂进这个列表，
# agent.py 侧无需任何改动。
ALL_TOOLS = [list_chats, get_stats, get_messages, search_messages, summarize_chat]
