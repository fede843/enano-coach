from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorCode = Literal[
    "INVALID_QUERY",
    "INVALID_CURSOR",
    "CURSOR_CONTEXT_MISMATCH",
    "SESSION_REQUIRED",
    "SESSION_EXPIRED",
    "ACCESS_PENDING",
    "ACCESS_BLOCKED",
    "FORBIDDEN",
    "NOT_FOUND",
    "METHOD_NOT_ALLOWED",
    "RUN_NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "CURSOR_EXPIRED",
    "INVALID_SCOPE",
    "RATE_LIMITED",
    "INTERNAL_ERROR",
    "UPSTREAM_INVALID",
    "UPSTREAM_UNAVAILABLE",
    "UPSTREAM_TIMEOUT",
]


SAFE_MESSAGES: dict[ErrorCode, str] = {
    "INVALID_QUERY": "The query is not valid.",
    "INVALID_CURSOR": "The cursor is not valid for this list.",
    "CURSOR_CONTEXT_MISMATCH": "The cursor does not match this list context.",
    "SESSION_REQUIRED": "A session is required for this query.",
    "SESSION_EXPIRED": "The session has expired.",
    "ACCESS_PENDING": "This account does not have access to this query yet.",
    "ACCESS_BLOCKED": "Access to this query is blocked.",
    "FORBIDDEN": "This request is not allowed.",
    "NOT_FOUND": "The requested resource was not found.",
    "METHOD_NOT_ALLOWED": "This method is not allowed.",
    "RUN_NOT_FOUND": "The requested verification was not found.",
    "IDEMPOTENCY_CONFLICT": "The request conflicts with an existing operation.",
    "CURSOR_EXPIRED": "The requested page expired; restart the list.",
    "INVALID_SCOPE": "The verification scope is not valid.",
    "RATE_LIMITED": "The request limit was reached.",
    "INTERNAL_ERROR": "The request could not be completed.",
    "UPSTREAM_INVALID": "The source returned an invalid response.",
    "UPSTREAM_UNAVAILABLE": "The source is unavailable; query again manually.",
    "UPSTREAM_TIMEOUT": "The source took too long to respond.",
}


@dataclass(frozen=True)
class BFFError(Exception):
    code: ErrorCode
    status_code: int
    field: str | None = None
    retryable: bool = False
    retry_after: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code)

    @property
    def message(self) -> str:
        return SAFE_MESSAGES[self.code]


STATUS_BY_CODE: dict[ErrorCode, int] = {
    "INVALID_QUERY": 400,
    "INVALID_CURSOR": 400,
    "CURSOR_CONTEXT_MISMATCH": 400,
    "SESSION_REQUIRED": 401,
    "SESSION_EXPIRED": 401,
    "ACCESS_PENDING": 403,
    "ACCESS_BLOCKED": 403,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "RUN_NOT_FOUND": 404,
    "IDEMPOTENCY_CONFLICT": 409,
    "CURSOR_EXPIRED": 410,
    "INVALID_SCOPE": 422,
    "RATE_LIMITED": 429,
    "INTERNAL_ERROR": 500,
    "UPSTREAM_INVALID": 502,
    "UPSTREAM_UNAVAILABLE": 503,
    "UPSTREAM_TIMEOUT": 504,
}


def error_for(
    code: ErrorCode,
    *,
    field: str | None = None,
    retry_after: int | None = None,
) -> BFFError:
    return BFFError(
        code=code,
        status_code=STATUS_BY_CODE[code],
        field=field,
        retryable=retry_after is not None
        or code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_TIMEOUT"},
        retry_after=retry_after,
    )
