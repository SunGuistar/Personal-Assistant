"""每日一问持久化；问答正文不写日志。"""
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..exceptions import DomainError
from ..models.daily_question import DailyQuestion


def list_questions(session: Session):
    return list(session.scalars(select(DailyQuestion).order_by(DailyQuestion.id.desc())))


def create_question(session: Session, question: str, answer: str):
    item = DailyQuestion(question=question, answer=answer)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def update_question(session: Session, question_id: int, question: str, answer: str):
    item = session.get(DailyQuestion, question_id)
    if item is None:
        raise DomainError("问答不存在", code="daily_question_not_found", status_code=404)
    item.question = question
    item.answer = answer
    session.commit()
    session.refresh(item)
    return item
