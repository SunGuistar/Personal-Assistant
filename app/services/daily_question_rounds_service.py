"""按北京时间保存每日题单；不保存问答正文副本。"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..exceptions import DomainError
from ..models.daily_question import DailyQuestion, DailyQuestionRound
from .daily_questions_service import review_question


def _now():
    return datetime.now(timezone(timedelta(hours=8)))


def _get_round(session: Session):
    now = _now()
    day = now.date().isoformat()
    row = session.scalar(select(DailyQuestionRound).where(DailyQuestionRound.review_date == day))
    if row is None:
        items = list(session.scalars(select(DailyQuestion)))
        eligible = [q for q in items if not q.due_at or datetime.fromisoformat(q.due_at) <= now]
        eligible.sort(key=lambda q: (datetime.fromisoformat(q.due_at).timestamp() if q.due_at else float("inf"), q.id))
        row = DailyQuestionRound(review_date=day, queue_json=json.dumps([q.id for q in eligible]), total=len(eligible))
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.scalar(select(DailyQuestionRound).where(DailyQuestionRound.review_date == day))
            if row is None:
                raise
    return row


def _result(session: Session, row: DailyQuestionRound):
    ids = json.loads(row.queue_json)
    items = {q.id: q for q in session.scalars(select(DailyQuestion).where(DailyQuestion.id.in_(ids)))} if ids else {}
    return dict(review_date=row.review_date, version=row.version, total=row.total,
                completed=row.completed, queue=[items[i] for i in ids],
                has_questions=bool(session.scalar(select(func.count()).select_from(DailyQuestion))))


def today(session: Session):
    return _result(session, _get_round(session))


def review_today(session: Session, question_id: int, remembered: bool, review_date: str, version: int):
    row = _get_round(session)
    ids = json.loads(row.queue_json)
    if review_date != row.review_date or version != row.version or not ids or ids[0] != question_id:
        raise DomainError("题单已更新，请重试", code="daily_round_conflict", status_code=409)
    remaining = ids[1:] if remembered else ids[1:] + ids[:1]
    changed = session.execute(update(DailyQuestionRound).where(
        DailyQuestionRound.id == row.id, DailyQuestionRound.version == version,
    ).values(queue_json=json.dumps(remaining), completed=row.completed + int(remembered), version=version + 1))
    if changed.rowcount != 1:
        session.rollback()
        raise DomainError("题单已更新，请重试", code="daily_round_conflict", status_code=409)
    try:
        review_question(session, question_id, remembered, commit=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(row)
    return _result(session, row)
