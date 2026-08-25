"""Explicit database and unit-of-work boundary for the BFF control plane.

The running synthetic BFF does not construct this object.  A later runtime
wave must opt in through :class:`ControlPlaneSettings`, which validates the
server-only PostgreSQL URL before this module creates an engine.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from .control_plane_config import ControlPlaneSettings, _validate_app_database_url

if TYPE_CHECKING:
    from .control_plane_repositories import ControlPlaneRepositories


class ControlPlaneDisabledError(RuntimeError):
    """Raised when durable control-plane storage is used while disabled."""


class ControlPlaneConfigurationError(ValueError):
    """Raised when a database boundary cannot be built safely."""


_PRODUCTION_CONSTRUCTION_TOKEN = object()
_TEST_CONSTRUCTION_TOKEN = object()


class _ControlPlaneUnitOfWork(AbstractContextManager["_ControlPlaneUnitOfWork"]):
    """Commit one repository operation group or roll it back completely."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._now = now
        self.session: Session | None = None
        self.repositories: ControlPlaneRepositories | None = None
        self._active_token: object | None = None
        self._invalidated = False

    def __enter__(self) -> _ControlPlaneUnitOfWork:
        if self.session is not None:
            raise RuntimeError("control-plane unit of work is already open")
        active_token = object()
        self._active_token = active_token
        self._invalidated = False
        try:
            self.session = self._session_factory()
            from .control_plane_repositories import ControlPlaneRepositories

            self.repositories = ControlPlaneRepositories(
                self.session,
                now=self._now,
                is_open=lambda: (
                    self._active_token is active_token
                    and self.session is not None
                    and not self._invalidated
                ),
                invalidate=self.invalidate,
            )
        except BaseException:
            self._active_token = None
            if self.session is not None:
                self.session.close()
            self.session = None
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        del exception, traceback
        session = self.session
        if session is None:
            return False

        try:
            if exception_type is None and not self._invalidated:
                try:
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
            else:
                session.rollback()
        finally:
            self._active_token = None
            session.close()
            self.session = None
            self.repositories = None
        return False

    def invalidate(self) -> None:
        """Prevent a unit of work with a failed mutation from committing."""

        self._invalidated = True


class _ControlPlaneDatabase:
    """Own an explicitly constructed engine and session factory."""

    def __init__(
        self,
        engine: Engine,
        *,
        now: Callable[[], datetime],
        _construction_token: object | None = None,
    ) -> None:
        if not isinstance(engine, Engine):
            raise ControlPlaneConfigurationError("engine must be a SQLAlchemy Engine")
        if _construction_token not in {
            _PRODUCTION_CONSTRUCTION_TOKEN,
            _TEST_CONSTRUCTION_TOKEN,
        }:
            raise ControlPlaneConfigurationError(
                "use a validated control-plane database factory"
            )
        self.engine = engine
        self._now = now
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )

    def unit_of_work(self) -> _ControlPlaneUnitOfWork:
        """Return a context manager for one repository transaction."""

        return _ControlPlaneUnitOfWork(self.session_factory, now=self._now)

    def dispose(self) -> None:
        """Close pooled connections owned by this database boundary."""

        self.engine.dispose()


def create_control_plane_database(
    settings: ControlPlaneSettings,
) -> _ControlPlaneDatabase:
    """Create storage only from validated, enabled server-side settings."""

    if not isinstance(settings, ControlPlaneSettings):
        raise ControlPlaneConfigurationError(
            "settings must be a ControlPlaneSettings instance"
        )
    if not settings.enabled:
        raise ControlPlaneDisabledError("control-plane storage is disabled")

    try:
        app_database_url = _validate_app_database_url(settings.app_database_url)
    except ValueError:
        raise ControlPlaneConfigurationError("APP_DATABASE_URL is invalid") from None
    if app_database_url is None:
        raise ControlPlaneConfigurationError(
            "APP_DATABASE_URL is required when control plane is enabled"
        )

    try:
        engine = create_engine(app_database_url, future=True, pool_pre_ping=True)
    except (ArgumentError, ImportError, TypeError):
        raise ControlPlaneConfigurationError("APP_DATABASE_URL is invalid") from None
    return _ControlPlaneDatabase(
        engine,
        now=_utc_now,
        _construction_token=_PRODUCTION_CONSTRUCTION_TOKEN,
    )


def _create_test_control_plane_database(
    engine: Engine,
    *,
    now: Callable[[], datetime],
) -> _ControlPlaneDatabase:
    """Build an in-memory SQLite boundary for offline repository tests only."""

    if not isinstance(engine, Engine):
        raise ControlPlaneConfigurationError("engine must be a SQLAlchemy Engine")
    if engine.url.get_backend_name() != "sqlite" or engine.url.database not in {
        None,
        "",
        ":memory:",
    }:
        raise ControlPlaneConfigurationError(
            "test control-plane storage must use in-memory SQLite"
        )
    return _ControlPlaneDatabase(
        engine,
        now=now,
        _construction_token=_TEST_CONSTRUCTION_TOKEN,
    )


def _utc_now() -> datetime:
    from .control_plane import utc_now

    return utc_now()


__all__ = [
    "ControlPlaneConfigurationError",
    "ControlPlaneDisabledError",
    "create_control_plane_database",
]
