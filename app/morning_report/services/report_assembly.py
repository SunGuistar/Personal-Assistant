"""个人回顾和建议的确定性排版，不调用模型、不新增分析结论。"""
import re


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _title(value):
    return re.sub(r"([\\`*_\[\]])", r"\\\1", _text(value))


YESTERDAY_GROUPS = ("completed", "goal_progress", "attention", "questions", "additional")


def validate_yesterday(value, records: dict) -> dict:
    """校验 Agent 最终回顾，不改写标题、摘要、顺序或分组。"""
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("invalid yesterday_report schema")
    result = {"version": 1}
    ids = set()
    for group in YESTERDAY_GROUPS:
        rows = value.get(group)
        if not isinstance(rows, list):
            raise ValueError("invalid yesterday_report group")
        result[group] = []
        for item in rows:
            if not isinstance(item, dict) or any(not isinstance(item.get(key), str) for key in ("id", "title", "summary", "detail", "kind")):
                raise ValueError("invalid yesterday_report item")
            if not item["id"].strip() or item["id"] in ids or not item["title"].strip() or not item["summary"].strip():
                raise ValueError("invalid yesterday_report identity or text")
            ids.add(item["id"])
            refs = item.get("evidence_ids")
            if item["kind"] not in ("confirmed", "analysis", "unknown") or not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in records for ref in refs):
                raise ValueError("invalid yesterday_report evidence")
            if (item["kind"] != "unknown" and not refs) or (group not in ("questions", "additional") and item["kind"] == "unknown"):
                raise ValueError("unsupported yesterday_report claim")
            result[group].append(dict(item))
    notices = value.get("notices")
    if not isinstance(notices, list) or any(not isinstance(item, str) for item in notices):
        raise ValueError("invalid yesterday_report notices")
    result["notices"] = list(notices)
    return result


def build_yesterday(personal: dict, goal: dict) -> dict:
    """新报告直接使用目标分析 Agent 的最终回顾；旧报告保留兼容。"""
    report = (goal.get("analysis") or {}).get("yesterday_report")
    if goal.get("status") == "ok" and isinstance(report, dict):
        return report
    if goal.get("yesterday_error"):
        return _legacy_build_yesterday(personal, {"status": "failed", "error": goal["yesterday_error"]})
    return _legacy_build_yesterday(personal, goal)


def _legacy_build_yesterday(personal: dict, goal: dict) -> dict:
    """按证据分组，保留完整原文；展示数量由前端控制。"""
    result = {"version": 1, "completed": [], "goal_progress": [], "attention": [],
              "questions": [], "additional": [], "notices": []}
    completed_ids = set()

    def entry(item, content, kind, key):
        full = _text(content)
        title = _text(item.get("title")) or re.split(r"[。；，：]", full)[0]
        if len(title) > 22:
            title = title[:21] + "…"
        sentence = re.split(r"(?<=[。！？])", full)[0]
        return {"id": key, "title": title, "summary": sentence,
                "detail": full + (("\n" + _text(item["detail"])) if item.get("detail") and _text(item["detail"]) != full else ""), "kind": kind,
                "evidence_ids": item.get("evidence_ids") or []}

    for index, item in enumerate(personal.get("daily_done", [])):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        source_id = item.get("source_id") or (f"daily_tasks:{item['id']}" if item.get("id") else None)
        if source_id:
            completed_ids.add(source_id)
        result["completed"].append(entry(item, item.get("description") or item["title"],
                                          "confirmed", f"completed:{index}"))
    if goal.get("status") == "failed":
        result["notices"].append("目标分析暂缺（" + _text(goal.get("error") or "未知错误") + "），仅展示已有个人记录。")
    if goal.get("status") == "ok":
        analysis = goal.get("analysis") or {}
        seen = set()
        for field in ("progress", "goal_observations", "risks", "questions", "associations"):
            for index, item in enumerate(analysis.get(field, [])):
                if not isinstance(item, dict) or not _text(item.get("content")):
                    continue
                content = _text(item["content"])
                kind = item.get("kind") if item.get("kind") in ("confirmed", "analysis") else "unknown"
                refs = item.get("evidence_ids") or []
                valid_refs = isinstance(refs, list) and all(isinstance(ref, str) for ref in refs)
                group = "goal_progress"
                if field == "questions" or kind == "unknown" or not valid_refs or not refs:
                    group = "questions"
                elif field == "risks":
                    group = "attention"
                elif field == "associations" or content in seen or (completed_ids and set(refs) <= completed_ids):
                    group = "additional"
                result[group].append(entry(item, content, kind, f"{field}:{index}"))
                seen.add(content)
        current = analysis.get("current_state")
        if not any(result[key] for key in ("completed", "goal_progress", "attention", "questions", "additional")) and isinstance(current, dict) and current.get("content"):
            result["questions"].append(entry(current, current["content"], "unknown", "current_state"))
        for index, gap in enumerate(analysis.get("data_gaps") or []):
            if isinstance(gap, str) and gap.strip():
                result["questions"].append(entry({}, gap, "unknown", f"gap:{index}"))
    if not any(result[key] for key in ("completed", "goal_progress", "attention", "questions", "additional")):
        result["notices"].append("本轮记录不足，不能据此认定昨日没有进展。")
    return result


def display_yesterday(mr, version, sections: dict) -> dict:
    """旧报告仅从同轮快照补齐展示，不写回历史数据。"""
    if isinstance(sections.get("yesterday_content"), dict):
        return sections
    from sqlalchemy import select
    from ..models import PersonalEventSnapshot
    snapshots = mr.execute(select(PersonalEventSnapshot).where(
        PersonalEventSnapshot.run_id == version.run_id,
        PersonalEventSnapshot.source_table == "daily_tasks")).scalars().all()
    if snapshots or isinstance(sections.get("goal"), dict):
        personal = {"daily_done": [dict(row.payload or {}, source_id=f"daily_tasks:{row.record_id}") for row in snapshots]}
        sections = dict(sections, yesterday_content=build_yesterday(personal, sections.get("goal") or {}))
    return sections


def personal_sections(personal: dict, goal: dict, advice: dict) -> tuple[str, str]:
    content = build_yesterday(personal, goal)
    yesterday = list(content["notices"])
    for key, label in (("completed", "昨日完成"), ("goal_progress", "目标推进"),
                       ("attention", "需要关注"), ("questions", "待确认"), ("additional", "更多分析")):
        if content[key]:
            yesterday.append("### " + label)
            for item in content[key]:
                body = item["summary"]
                if item["detail"] and item["detail"] != body:
                    body += "\n  " + item["detail"].replace("\n", "\n  ")
                yesterday.append(f"- **{_title(item['title'])}**。{body}")
    actions = []
    if advice.get("status") == "failed":
        actions.append("暂未生成可发布的建议：建议分析失败（" + _text(advice.get("error") or "未知错误") + "）。")
    else:
        for item in advice.get("advices", [])[:3]:
            if not isinstance(item, dict) or not item.get("content"): continue
            priority = _text(item.get("priority"))
            actions.append(f"{len(actions) + 1}. **{_title(item['content'])}**" + (f"（{priority}）" if priority else "") +
                "\n   - 依据：" + _text(item.get("basis")) + "\n   - 下一步：" + _text(item.get("next_step")))
        if not actions:
            actions.append("暂无有足够个人依据的行动建议。")
        if advice.get("note"):
            actions.append("\n说明：" + _text(advice["note"]))
    return "\n".join(yesterday), "\n\n".join(actions)
