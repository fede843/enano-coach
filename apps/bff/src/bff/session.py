from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .errors import error_for


@dataclass(frozen=True)
class SessionContext:
    """Server-selected synthetic session; no browser identifier is consulted."""

    session_key: str
    mode: str
    authenticated: bool
    access_state: str
    can_read_verification: bool


def session_from_settings(settings: Settings) -> SessionContext:
    mode = settings.session_mode
    if mode == "active":
        return SessionContext(settings.session_key, mode, True, "active", True)
    if mode == "pending":
        return SessionContext(settings.session_key, mode, True, "pending", False)
    if mode == "blocked":
        return SessionContext(settings.session_key, mode, True, "blocked", False)
    return SessionContext(
        settings.session_key,
        mode,
        False,
        "anonymous",
        False,
    )


def require_active_session(session: SessionContext) -> SessionContext:
    if session.mode == "expired":
        raise error_for("SESSION_EXPIRED")
    if session.mode == "anonymous":
        raise error_for("SESSION_REQUIRED")
    if session.mode == "pending":
        raise error_for("ACCESS_PENDING")
    if session.mode == "blocked":
        raise error_for("ACCESS_BLOCKED")
    if not session.can_read_verification:
        raise error_for("FORBIDDEN")
    return session
