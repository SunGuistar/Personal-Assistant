"""两类决策 Agent 的只读工具：来源可追溯，失败显式返回，普通日志只记录计数。"""
from __future__ import annotations
import json
import re
from langchain_core.tools import tool


def evidence_records(personal):
    out = {}
    for key, values in personal.items():
        if isinstance(values, list):
            for record in values:
                if isinstance(record, dict) and record.get("source_id"):
                    out[record["source_id"]] = record
    return out


def _relevance(query, record):
    text = json.dumps(record, ensure_ascii=False).casefold()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2}", query.casefold())
    return sum(token in text for token in tokens)


def make_tools(personal, stage, tracker=None,
               on_evidence=None, cancel_check=None):
    known = evidence_records(personal)

    def finish(name, records, error=None):
        if on_evidence:
            on_evidence(records)
        if tracker:
            tracker.stage_progress(stage, summary=f"工具 {name}：返回 {len(records)} 条" + ("（检索失败）" if error else ""),
                data={"last_tool": name, "last_result_count": len(records), "retrieval_failed": bool(error)})
        return json.dumps({"records": records, "error": error,
                           "status": "failed" if error else "ok"}, ensure_ascii=False)

    def personal_search(query):
        ranked = sorted(((r, _relevance(query, r)) for r in known.values()), key=lambda pair: pair[1], reverse=True)
        return [{**r, "relevance_basis": "查询词匹配个人记录", "relevance_score": score}
                for r, score in ranked if score > 0][:8]

    @tool
    def search_personal_records(query: str) -> str:
        """只读检索当前快照中的任务、目标、备忘与阅读元数据；返回来源 ID、时间和相关性。"""
        if cancel_check:
            cancel_check()
        return finish("personal_records", personal_search(query[:500]))

    @tool
    def search_task_status(query: str) -> str:
        """查找当前快照中相关任务的真实完成/未完成记录，不推断未记录的执行情况。"""
        if cancel_check:
            cancel_check()
        return finish("task_status", [r for r in personal_search(query[:500]) if r["source_id"].startswith("daily_tasks:")])

    return [search_personal_records] if stage == "goal_analysis" else [
        search_personal_records, search_task_status]
