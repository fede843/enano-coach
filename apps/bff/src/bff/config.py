from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

SESSION_MODES = frozenset({"anonymous", "pending", "blocked", "expired", "active"})
LOCAL_DEVELOPMENT_ENVIRONMENTS = frozenset({"local", "development", "test"})
DEFAULT_SESSION_KEY = "synthetic-session-active"
DEFAULT_ALLOWED_ORIGINS = frozenset({"http://localhost:5173", "http://testserver"})


def _is_local_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
        "testserver",
    }


@dataclass(frozen=True)
class Settings:
    environment: str
    session_mode: str
    session_key: str
    allowed_origins: frozenset[str]
    cursor_ttl_seconds: int
    fixture_case: str | None

    @classmethod
    def from_environment(
        cls,
        *,
        environment: str | None = None,
        session_mode: str | None = None,
        session_key: str | None = None,
        allowed_origin: str | None = None,
        cursor_ttl_seconds: int | None = None,
        fixture_case: str | None = None,
    ) -> Settings:
        selected_mode = session_mode or os.getenv(
            "BFF_SYNTHETIC_SESSION_MODE", "active"
        )
        if selected_mode not in SESSION_MODES:
            raise ValueError("BFF_SYNTHETIC_SESSION_MODE is not supported")

        configured_environment = (
            environment if environment is not None else os.getenv("BFF_ENVIRONMENT")
        )
        if not configured_environment:
            if selected_mode == "active":
                raise ValueError("BFF_ENVIRONMENT is required")
            # Non-active synthetic modes have no protected access. Keep the
            # process explicitly non-active rather than enabling local access.
            selected_environment = "test"
        else:
            selected_environment = configured_environment
        if (
            selected_mode == "active"
            and selected_environment not in LOCAL_DEVELOPMENT_ENVIRONMENTS
        ):
            raise ValueError(
                "synthetic active sessions require a local development environment"
            )

        configured_origins = allowed_origin or os.getenv("BFF_ALLOWED_ORIGINS")
        origins = (
            frozenset(
                origin.strip()
                for origin in configured_origins.split(",")
                if origin.strip()
            )
            if configured_origins
            else DEFAULT_ALLOWED_ORIGINS
        )
        if not origins:
            origins = DEFAULT_ALLOWED_ORIGINS
        if any(not _is_local_origin(origin) for origin in origins):
            raise ValueError("synthetic sessions require local origins")

        configured_ttl = cursor_ttl_seconds
        if configured_ttl is None:
            configured_ttl = int(os.getenv("BFF_CURSOR_TTL_SECONDS", "300"))
        configured_ttl = max(0, min(configured_ttl, 86_400))

        return cls(
            environment=selected_environment,
            session_mode=selected_mode,
            session_key=session_key
            or os.getenv("BFF_SYNTHETIC_SESSION_KEY", DEFAULT_SESSION_KEY),
            allowed_origins=origins,
            cursor_ttl_seconds=configured_ttl,
            fixture_case=(
                fixture_case
                if fixture_case is not None
                else os.getenv("BFF_SYNTHETIC_FIXTURE_CASE")
            ),
        )
