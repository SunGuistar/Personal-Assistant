"""统一错误格式：{detail: {code, message}}（ARCH §4）。

服务层抛领域异常，API 层统一映射；后台任务异常落任务表，不在此处抛出。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DomainError(RuntimeError):
    """业务领域异常基类。message 面向用户可读，不含敏感细节。"""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class TaskConflict(DomainError):
    """同类型同参数任务正在执行（重复提交保护）。"""

    status_code = 409
    code = "task_conflict"


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


def error_body(code: str, message: str) -> dict:
    return {"detail": {"code": code, "message": message}}


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, str(exc)))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", []) if part not in ("body", "query", "path"))
    message = f"参数校验失败: {loc} {first.get('msg', '')}".strip()
    return JSONResponse(status_code=422, content=error_body("validation_error", message))


async def not_found_handler(request: Request, exc) -> JSONResponse:
    return JSONResponse(status_code=404, content=error_body("not_found", f"资源不存在: {request.url.path}"))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(404, not_found_handler)
