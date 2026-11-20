"""每日一问持久化；问答正文不写日志。"""
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from ..exceptions import DomainError
from ..models.daily_question import DailyQuestion, DailyQuestionRound


def list_questions(session: Session):
    return list(session.scalars(select(DailyQuestion).order_by(DailyQuestion.id.desc())))


def create_question(session: Session, question: str, answer: str, tags: str | None = None):
    item = DailyQuestion(question=question, answer=answer, tags=tags or "")
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def update_question(session: Session, question_id: int, question: str, answer: str, tags: str | None = None):
    item = session.get(DailyQuestion, question_id)
    if item is None:
        raise DomainError("问答不存在", code="daily_question_not_found", status_code=404)
    if item.question != question or item.answer != answer:
        item.review_level = 0
        item.due_at = None
    if tags is not None:
        item.tags = tags
    item.question = question
    item.answer = answer
    session.commit()
    session.refresh(item)
    return item



def delete_question(session: Session, question_id: int, *, confirmed: bool):
    """人工审核确认后删除问答，同一事务移除所有未完成题单引用。"""
    if confirmed is not True:
        raise DomainError("请先审核并确认删除问答", code="delete_confirmation_required", status_code=400)
    item = session.get(DailyQuestion, question_id)
    if item is None:
        raise DomainError("问答不存在", code="daily_question_not_found", status_code=404)
    try:
        for row in session.scalars(select(DailyQuestionRound)):
            ids = json.loads(row.queue_json)
            remaining = [value for value in ids if value != question_id]
            removed = len(ids) - len(remaining)
            if not removed:
                continue
            changed = session.execute(update(DailyQuestionRound).where(
                DailyQuestionRound.id == row.id, DailyQuestionRound.version == row.version,
            ).values(queue_json=json.dumps(remaining), total=row.total - removed, version=row.version + 1))
            if changed.rowcount != 1:
                raise DomainError("题单已更新，请重试删除", code="daily_round_conflict", status_code=409)
        session.delete(item)
        session.commit()
    except Exception:
        session.rollback()
        raise


def review_question(session: Session, question_id: int, remembered: bool, *, commit: bool = True):
    from datetime import datetime, timedelta, timezone
    item = session.get(DailyQuestion, question_id)
    if item is None:
        raise DomainError("问答不存在", code="daily_question_not_found", status_code=404)
    now = datetime.now(timezone(timedelta(hours=8)))
    intervals = (1, 3, 7, 14, 30)
    level = min(max(item.review_level, 0), len(intervals) - 1)
    item.due_at = (now + (timedelta(days=intervals[level]) if remembered else timedelta(minutes=10))).isoformat()
    item.review_level = min(level + 1, len(intervals) - 1) if remembered else 0
    item.review_count = DailyQuestion.review_count + 1
    if remembered:
        item.remembered_count = DailyQuestion.remembered_count + 1
    else:
        item.forgotten_count = DailyQuestion.forgotten_count + 1
    if commit:
        session.commit()
        session.refresh(item)
    return item
