"""每日一问 API。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .deps import get_session
from ..schemas.daily_question import DailyQuestionIn, DailyQuestionOut
from ..services import daily_questions_service as service

router = APIRouter(prefix="/daily_questions", tags=["daily_questions"])


@router.get("", response_model=list[DailyQuestionOut])
def list_questions(session: Session = Depends(get_session)):
    return service.list_questions(session)


@router.post("", response_model=DailyQuestionOut, status_code=201)
def create_question(payload: DailyQuestionIn, session: Session = Depends(get_session)):
    return service.create_question(session, **payload.model_dump())


@router.put("/{question_id}", response_model=DailyQuestionOut)
def update_question(question_id: int, payload: DailyQuestionIn, session: Session = Depends(get_session)):
    return service.update_question(session, question_id, **payload.model_dump())


from pydantic import BaseModel, StrictBool


class ReviewIn(BaseModel):
    remembered: StrictBool


@router.post("/{question_id}/review", response_model=DailyQuestionOut)
def review_question(question_id: int, payload: ReviewIn, session: Session = Depends(get_session)):
    return service.review_question(session, question_id, payload.remembered)
