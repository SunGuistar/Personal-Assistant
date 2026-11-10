"""数据清理审核 API（阶段 5，D4）。

- 全部删除入口必须经人工勾选 + 二次确认（confirm 生成计划，execute 需 confirmed_at）；
- 与 wechat.sync 互斥（双向 409）；执行走 TaskRunner（kind cleanup.execute）；
- 无任何自动删除入口；候选生成与预览严格只读。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..cleanup import service
from ..cleanup.service import ACTIVE_TASK_KINDS_BLOCKING_CLEANUP, CLEANUP_TASK_KIND
from ..exceptions import DomainError
from ..schemas.cleanup import (
    CleanupRulesOut,
    CleanupStatusOut,
    ConfirmIn,
    ExecuteIn,
    ExecuteOut,
    RetryIn,
    ReviewOut,
)
from .deps import get_session, get_settings, get_task_runner

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


def _protected(request: Request) -> list[str]:
    return request.app.state.settings.protected_date_list


@router.get("/status", response_model=CleanupStatusOut)
def status(request: Request, session: Session = Depends(get_session)):
    """本周审核状态（首页横幅用）；访问时惰性确保本周审核记录存在。"""

    service.ensure_review(
        session,
        today=date.today(),
        protected=_protected(request),
    )
    return service.cleanup_status(session)


@router.get("/rules", response_model=CleanupRulesOut)
def rules(request: Request):
    """当前实际生效的清理审核规则（审核页完整展示，与执行逻辑同源）。"""

    return service.cleanup_rules(service.KEEP_DAYS, _protected(request))


@router.get("/reviews", response_model=list[ReviewOut])
def reviews(session: Session = Depends(get_session)):
    return service.list_reviews(session)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def review(review_id: int, session: Session = Depends(get_session)):
    return service.review_to_dict(session, service.get_review(session, review_id))


@router.post("/reviews/{review_id}/dismiss", response_model=ReviewOut)
def dismiss(review_id: int, session: Session = Depends(get_session)):
    """稍后：仅隐藏提醒，不结束周期。"""

    return service.dismiss_review(session, review_id)


@router.post("/reviews/{review_id}/skip", response_model=ReviewOut)
def skip(review_id: int, session: Session = Depends(get_session)):
    """跳过本次：结束本周期审核（数据保留，不产生删除）。"""

    return service.skip_review(session, review_id)


@router.post("/reviews/{review_id}/confirm", response_model=ReviewOut)
def confirm(review_id: int, payload: ConfirmIn, request: Request, session: Session = Depends(get_session)):
    """二次确认后生成删除计划（明细落库，仍不删数据）。"""

    return service.confirm_review(
        session, review_id, payload.candidate_ids, protected=_protected(request)
    )


@router.post("/execute", response_model=ExecuteOut, status_code=202)
def execute(payload: ExecuteIn, request: Request, session: Session = Depends(get_session), runner=Depends(get_task_runner)):
    """提交删除执行 job（需已确认；与 wechat.sync 互斥；同 kind 防重）。"""

    review = service.get_review(session, payload.review_id)
    if not review.confirmed_at:
        raise DomainError("该审核未经确认，拒绝执行删除", code="review_not_confirmed", status_code=409)
    if service.active_task_exists(session, list(ACTIVE_TASK_KINDS_BLOCKING_CLEANUP)):
        raise DomainError("微信同步正在进行，清理需等待同步完成", code="sync_conflict", status_code=409)

    protected = _protected(request)
    session_factory = request.app.state.session_factory

    def job(_progress_cb):
        with session_factory() as job_session:
            return service.execute_review(job_session, review.id, protected=protected)

    task = runner.submit(CLEANUP_TASK_KIND, {"review_id": review.id}, job)
    return {"task_id": task.id, "status": task.status}


@router.post("/retry", response_model=ReviewOut)
def retry(payload: RetryIn, session: Session = Depends(get_session)):
    """失败分组重置（幂等重试需再次提交 execute）。"""

    service.retry_candidates(session, payload.review_id, payload.candidate_ids)
    return service.review_to_dict(session, service.get_review(session, payload.review_id))
