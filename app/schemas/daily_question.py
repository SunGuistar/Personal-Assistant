"""每日一问输入与输出。"""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, StringConstraints

QuestionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]


class DailyQuestionIn(BaseModel):
    question: QuestionText
    answer: AnswerText
    tags: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class DailyQuestionOut(DailyQuestionIn):
    model_config = ConfigDict(from_attributes=True)
    review_level: int
    review_count: int
    remembered_count: int
    forgotten_count: int
    due_at: str | None
    id: int
    created_at: str
    updated_at: str


class DailyQuestionRoundOut(BaseModel):
    review_date: str
    version: int
    total: int
    completed: int
    queue: list[DailyQuestionOut]
    has_questions: bool
