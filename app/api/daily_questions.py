"""每日一问 API。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.orm import Session
from .deps import get_session
from ..schemas.daily_question import DailyQuestionIn, DailyQuestionOut, DailyQuestionRoundOut
from ..services import daily_questions_service as service
from ..services import daily_question_rounds_service as rounds

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


class ReviewIn(BaseModel):
    remembered: StrictBool


class DailyReviewIn(ReviewIn):
    question_id: int
    review_date: str
    version: int = Field(ge=0)


@router.get("/today", response_model=DailyQuestionRoundOut)
def today(session: Session = Depends(get_session)):
    return rounds.today(session)


@router.post("/today/review", response_model=DailyQuestionRoundOut)
def review_today(payload: DailyReviewIn, session: Session = Depends(get_session)):
    return rounds.review_today(session, **payload.model_dump())


@router.post("/{question_id}/review", response_model=DailyQuestionOut)
def review_question(question_id: int, payload: ReviewIn, session: Session = Depends(get_session)):
    return service.review_question(session, question_id, payload.remembered)
