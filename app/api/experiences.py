"""经验库 API：只提供列表、新增及编辑。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from .deps import get_session
from ..services import experiences as service

router = APIRouter(prefix="/experiences", tags=["experiences"])


class ExperienceIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    problem: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]
    solution: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]
    tags: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class ExperienceOut(ExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: str
    updated_at: str


@router.get("", response_model=list[ExperienceOut])
def list_experiences(session: Session = Depends(get_session)):
    return service.list_experiences(session)


@router.post("", response_model=ExperienceOut, status_code=201)
def create_experience(payload: ExperienceIn, session: Session = Depends(get_session)):
    return service.save_experience(session, payload.model_dump())


@router.put("/{experience_id}", response_model=ExperienceOut)
def update_experience(experience_id: int, payload: ExperienceIn, session: Session = Depends(get_session)):
    return service.save_experience(session, payload.model_dump(), experience_id)
