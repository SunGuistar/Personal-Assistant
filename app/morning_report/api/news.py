"""新闻重要标记接口。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictBool
from sqlalchemy.orm import Session
from .deps import get_mr_session
from ..services import news_importance

router = APIRouter()


class ImportanceIn(BaseModel):
    is_important: StrictBool


@router.get("/report/{version_id}/news")
def report_news(version_id: int, mr: Session = Depends(get_mr_session)) -> dict:
    return {"items": news_importance.report_news(mr, version_id)}


@router.patch("/news/{news_id}/importance")
def mark_importance(news_id: int, body: ImportanceIn, mr: Session = Depends(get_mr_session)) -> dict:
    return news_importance.set_importance(mr, news_id, body.is_important)
