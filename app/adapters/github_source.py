"""GitHub 官方 REST API 适配器（阶段一）。

- 认证：Token 从环境变量 GITHUB_TOKEN 读取（权威文件 ~/.personal-hub/.env，
  经 env_bootstrap.load_hub_env 加载）；Token 只存在于本进程，不进日志、不向前端暴露。
- 限流：429 或速率上限 403 时按 Retry-After / X-RateLimit-Reset 等待重试，
  最多 2 次（AGENTS §6）；其余 4xx/5xx 直接抛 GithubApiError，由任务层落库。
- 分页：list 接口 per_page=100 自动翻页，生成器惰性产出，调用方控制消费。
- 测试用 FakeClient（实现同签名方法）注入，零真实外网。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.github.com"
MAX_RETRIES = 2
DEFAULT_TIMEOUT = 20.0


class GithubApiError(RuntimeError):
    """GitHub API 可预期错误（状态码 + 人话消息，不含 Token）。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def token_configured() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN", "").strip())


def _require_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise GithubApiError("未配置 GITHUB_TOKEN，请在 ~/.personal-hub/.env 中设置后重试")
    return token


def _iso_utc(value: str | None) -> str:
    """GitHub 时间（ISO8601 Z）原样保留为 UTC 文本；缺失返回空串（不伪造）。"""

    return (value or "").strip()


class GithubClient:
    """GitHub REST 客户端。方法返回原始 dict，标准化在 service 层。"""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = (token or "").strip() or _require_token()
        self._owns_http = http is None
        self._http = http or httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # ---------- HTTP 基元 ----------

    def _sleep_for_retry(self, response: httpx.Response, attempt: int) -> bool:
        """限流类响应返回 True 并已按服务端指示等待；其他错误抛异常。"""
        status = response.status_code
        retry_after = response.headers.get("Retry-After")
        remaining = response.headers.get("X-RateLimit-Remaining")
        if status == 429 or (status == 403 and (retry_after or remaining == "0")):
            if attempt >= MAX_RETRIES:
                raise GithubApiError("GitHub API 限流中且重试次数已用尽，请稍后重试", status=status)
            if retry_after:
                wait = float(retry_after)
            else:
                reset = float(response.headers.get("X-RateLimit-Reset") or 0)
                wait = max(reset - time.time(), 1.0)
            wait = min(wait, 60.0)  # 上限保护：最长等 60s
            logger.warning("GitHub 限流，等待 %.0fs 后重试（第 %d 次）", wait, attempt + 1)
            time.sleep(wait)
            return True
        if status >= 400:
            raise GithubApiError(f"GitHub API 错误 HTTP {status}", status=status)
        return False

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        attempt = 0
        while True:
            response = self._http.get(f"{self.base_url}{path}", params=params or {})
            if self._sleep_for_retry(response, attempt):
                attempt += 1
                continue
            return response

    def _pages(self, path: str, params: dict[str, Any]) -> Iterator[list[dict]]:
        """自动翻页：直到空页或非 200。每页 list 交给调用方消费。"""

        page = 1
        while True:
            batch = self._get(path, {**params, "per_page": 100, "page": page}).json()
            if not isinstance(batch, list):
                raise GithubApiError(f"GitHub 响应格式异常（期望数组）: {path}")
            if not batch:
                return
            yield batch
            if len(batch) < 100:
                return
            page += 1

    # ---------- 业务端点 ----------

    def list_repos(self) -> list[dict]:
        """当前用户可见的全部仓库（含私有与 fork，个人开发活动口径）。"""

        repos: list[dict] = []
        for batch in self._pages("/user/repos", {"affiliation": "owner", "sort": "updated"}):
            repos.extend(batch)
        return repos

    def iter_commits(self, full_name: str, since: str = "") -> Iterator[dict]:
        """仓库提交（sha/author/message/authored date）。since 为 UTC ISO 游标。"""

        params: dict[str, Any] = {"sha": "HEAD"}
        if since:
            params["since"] = since
        for batch in self._pages(f"/repos/{full_name}/commits", params):
            yield from batch

    def iter_pull_requests(self, full_name: str, since: str = "") -> Iterator[dict]:
        """仓库 PR（state=all）；since 作用于 updated_at。"""

        params: dict[str, Any] = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            params["since"] = since
        for batch in self._pages(f"/repos/{full_name}/pulls", params):
            yield from batch

    def iter_issues(self, full_name: str, since: str = "") -> Iterator[dict]:
        """仓库 Issue；GitHub 该端点混含 PR，由 service 层按 pull_request 键过滤。"""

        params: dict[str, Any] = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            params["since"] = since
        for batch in self._pages(f"/repos/{full_name}/issues", params):
            yield from batch


def commit_fields(raw: dict) -> dict[str, Any]:
    """REST commit 条目 → 标准化字段（UTC 文本时间）。"""

    commit = raw.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": str(raw.get("sha") or ""),
        "author_name": str(author.get("name") or ""),
        "author_email": str(author.get("email") or ""),
        "message": str(commit.get("message") or "").strip(),
        "authored_at": _iso_utc(author.get("date")),
        "url": str(raw.get("html_url") or ""),
    }


def pull_fields(raw: dict) -> dict[str, Any]:
    user = raw.get("user") or {}
    return {
        "id": int(raw.get("id") or 0),
        "number": int(raw.get("number") or 0),
        "title": str(raw.get("title") or ""),
        "state": str(raw.get("state") or ""),
        "author": str(user.get("login") or ""),
        "created_at": _iso_utc(raw.get("created_at")),
        "closed_at": _iso_utc(raw.get("closed_at")) or None,
        "merged_at": _iso_utc(raw.get("merged_at")) or None,
        "url": str(raw.get("html_url") or ""),
    }


def issue_fields(raw: dict) -> dict[str, Any]:
    user = raw.get("user") or {}
    return {
        "id": int(raw.get("id") or 0),
        "number": int(raw.get("number") or 0),
        "title": str(raw.get("title") or ""),
        "state": str(raw.get("state") or ""),
        "author": str(user.get("login") or ""),
        "created_at": _iso_utc(raw.get("created_at")),
        "closed_at": _iso_utc(raw.get("closed_at")) or None,
        "url": str(raw.get("html_url") or ""),
    }


def repo_fields(raw: dict) -> dict[str, Any]:
    return {
        "id": int(raw.get("id") or 0),
        "name": str(raw.get("name") or ""),
        "full_name": str(raw.get("full_name") or ""),
        "private": 1 if raw.get("private") else 0,
        "fork": 1 if raw.get("fork") else 0,
        "description": str(raw.get("description") or ""),
        "default_branch": str(raw.get("default_branch") or ""),
        "language": str(raw.get("language") or "") or None,
        "created_at": _iso_utc(raw.get("created_at")),
        "updated_at": _iso_utc(raw.get("updated_at")),
    }
