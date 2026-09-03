from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import UUID

SESSION_MODES = frozenset({"anonymous", "pending", "blocked", "expired", "active"})
LOCAL_DEVELOPMENT_ENVIRONMENTS = frozenset({"local", "development", "test"})
DEV_ACCESS_ENVIRONMENTS = frozenset({"development", "test"})
DEFAULT_SESSION_KEY = "synthetic-session-active"
DEFAULT_ALLOWED_ORIGINS = frozenset({"http://localhost:5173", "http://testserver"})
_SYNTHETIC_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _is_local_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
        "testserver",
    }


def _synthetic_key(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not _SYNTHETIC_KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{name} is not a supported synthetic key")
    return value


def _boolean_setting(value: bool | str | None, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return False
    raise ValueError(f"{name} must be a boolean")


def _credential_setting(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{name} is not valid")
    return value


def _ow_user_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("BFF_SYNTHETIC_OW_USER_KEY must be a valid UUID")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError("BFF_SYNTHETIC_OW_USER_KEY must be a valid UUID") from exc


@dataclass(frozen=True)
class Settings:
    environment: str
    session_mode: str
    session_key: str = field(repr=False)
    principal_key: str = field(repr=False)
    owner_key: str = field(repr=False)
    ow_user_key: str = field(repr=False)
    allowed_origins: frozenset[str]
    cursor_ttl_seconds: int
    fixture_case: str | None
    dev_access_enabled: bool = False
    live_ow_enabled: bool = False
    live_ow_allow_private_http: bool = False
    ow_api_base_url: str | None = field(default=None, repr=False)
    ow_bearer_token: str | None = field(default=None, repr=False)
    ow_api_key: str | None = field(default=None, repr=False)
    ow_timeout_seconds: float = field(default=10.0, repr=False)

    @classmethod
    def from_environment(
        cls,
        *,
        environment: str | None = None,
        session_mode: str | None = None,
        dev_access_enabled: bool | str | None = None,
        session_key: str | None = None,
        principal_key: str | None = None,
        owner_key: str | None = None,
        ow_user_key: str | None = None,
        allowed_origin: str | None = None,
        cursor_ttl_seconds: int | None = None,
        fixture_case: str | None = None,
        live_ow_enabled: bool | str | None = None,
        live_ow_allow_private_http: bool | str | None = None,
        ow_api_base_url: str | None = None,
        ow_bearer_token: str | None = None,
        ow_api_key: str | None = None,
        ow_timeout_seconds: float | str | None = None,
    ) -> Settings:
        selected_mode = session_mode or os.getenv(
            "BFF_SYNTHETIC_SESSION_MODE", "active"
        )
        if selected_mode not in SESSION_MODES:
            raise ValueError("BFF_SYNTHETIC_SESSION_MODE is not supported")
        selected_dev_access_enabled = _boolean_setting(
            (
                dev_access_enabled
                if dev_access_enabled is not None
                else os.getenv("BFF_DEV_ACCESS_ENABLED")
            ),
            name="BFF_DEV_ACCESS_ENABLED",
        )
        selected_live_ow_enabled = _boolean_setting(
            (
                live_ow_enabled
                if live_ow_enabled is not None
                else os.getenv("BFF_LIVE_OW_ENABLED")
            ),
            name="BFF_LIVE_OW_ENABLED",
        )
        selected_live_ow_allow_private_http = _boolean_setting(
            (
                live_ow_allow_private_http
                if live_ow_allow_private_http is not None
                else os.getenv("BFF_LIVE_OW_ALLOW_PRIVATE_HTTP")
            ),
            name="BFF_LIVE_OW_ALLOW_PRIVATE_HTTP",
        )

        selected_session_key = _synthetic_key(
            session_key or os.getenv("BFF_SYNTHETIC_SESSION_KEY", DEFAULT_SESSION_KEY),
            name="BFF_SYNTHETIC_SESSION_KEY",
        )
        selected_principal_key = _synthetic_key(
            principal_key
            or os.getenv("BFF_SYNTHETIC_PRINCIPAL_KEY")
            or f"principal:{selected_session_key}",
            name="BFF_SYNTHETIC_PRINCIPAL_KEY",
        )
        configured_owner_key = owner_key or os.getenv("BFF_SYNTHETIC_OWNER_KEY")
        selected_owner_key = _synthetic_key(
            configured_owner_key or f"owner:{selected_session_key}",
            name="BFF_SYNTHETIC_OWNER_KEY",
        )
        selected_ow_user_key = _synthetic_key(
            ow_user_key
            or os.getenv("BFF_SYNTHETIC_OW_USER_KEY")
            or f"ow-link:{selected_session_key}",
            name="BFF_SYNTHETIC_OW_USER_KEY",
        )

        configured_environment = (
            environment if environment is not None else os.getenv("BFF_ENVIRONMENT")
        )
        if not configured_environment:
            if selected_mode == "active" or selected_dev_access_enabled:
                raise ValueError("BFF_ENVIRONMENT is required")
            # Non-active synthetic modes have no protected access. Keep the
            # process explicitly non-active rather than enabling local access.
            selected_environment = "test"
        else:
            selected_environment = configured_environment
        if selected_live_ow_allow_private_http and (
            not selected_live_ow_enabled
            or not selected_dev_access_enabled
            or selected_environment not in DEV_ACCESS_ENVIRONMENTS
        ):
            raise ValueError(
                "BFF_LIVE_OW_ALLOW_PRIVATE_HTTP requires live OW and dev access "
                "in development or test"
            )
        if (
            selected_dev_access_enabled
            and selected_environment not in DEV_ACCESS_ENVIRONMENTS
        ):
            raise ValueError(
                "BFF_DEV_ACCESS_ENABLED requires BFF_ENVIRONMENT=development or test"
            )
        if selected_dev_access_enabled and not configured_owner_key:
            raise ValueError(
                "BFF_SYNTHETIC_OWNER_KEY is required when "
                "BFF_DEV_ACCESS_ENABLED is enabled"
            )
        if (
            selected_mode == "active"
            and selected_environment not in LOCAL_DEVELOPMENT_ENVIRONMENTS
        ):
            raise ValueError(
                "synthetic active sessions require a local development environment"
            )

        configured_ow_user_key = ow_user_key or os.getenv("BFF_SYNTHETIC_OW_USER_KEY")
        configured_ow_base_url = ow_api_base_url or os.getenv("OW_API_BASE_URL")
        configured_ow_bearer_token = ow_bearer_token or os.getenv("OW_BEARER_TOKEN")
        configured_ow_api_key = ow_api_key or os.getenv("OW_API_KEY")
        if selected_live_ow_enabled:
            if not selected_dev_access_enabled:
                raise ValueError("BFF_LIVE_OW_ENABLED requires BFF_DEV_ACCESS_ENABLED")
            if selected_environment not in DEV_ACCESS_ENVIRONMENTS:
                raise ValueError(
                    "BFF_LIVE_OW_ENABLED requires BFF_ENVIRONMENT=development or test"
                )
            if not configured_ow_user_key:
                raise ValueError(
                    "BFF_SYNTHETIC_OW_USER_KEY is required when "
                    "BFF_LIVE_OW_ENABLED is enabled"
                )
            selected_ow_user_key = _ow_user_uuid(configured_ow_user_key)
            if (
                not isinstance(configured_ow_base_url, str)
                or not configured_ow_base_url
            ):
                raise ValueError(
                    "OW_API_BASE_URL is required when BFF_LIVE_OW_ENABLED is enabled"
                )
            if configured_ow_bearer_token:
                configured_ow_bearer_token = _credential_setting(
                    configured_ow_bearer_token,
                    name="OW_BEARER_TOKEN",
                )
            elif configured_ow_api_key:
                configured_ow_api_key = _credential_setting(
                    configured_ow_api_key,
                    name="OW_API_KEY",
                )
            else:
                raise ValueError(
                    "OW_BEARER_TOKEN or OW_API_KEY is required when "
                    "BFF_LIVE_OW_ENABLED is enabled"
                )

        configured_timeout = ow_timeout_seconds
        if configured_timeout is None:
            configured_timeout = os.getenv("OW_TIMEOUT_SECONDS", "10")
        try:
            selected_ow_timeout = float(configured_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("OW_TIMEOUT_SECONDS is not valid") from exc
        if (
            not selected_ow_timeout > 0
            or selected_ow_timeout > 60
            or selected_ow_timeout != selected_ow_timeout
        ):
            raise ValueError("OW_TIMEOUT_SECONDS is not valid")

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
            session_key=selected_session_key,
            principal_key=selected_principal_key,
            owner_key=selected_owner_key,
            ow_user_key=selected_ow_user_key,
            allowed_origins=origins,
            cursor_ttl_seconds=configured_ttl,
            fixture_case=(
                fixture_case
                if fixture_case is not None
                else os.getenv("BFF_SYNTHETIC_FIXTURE_CASE")
            ),
            dev_access_enabled=selected_dev_access_enabled,
            live_ow_enabled=selected_live_ow_enabled,
            live_ow_allow_private_http=selected_live_ow_allow_private_http,
            ow_api_base_url=configured_ow_base_url,
            ow_bearer_token=configured_ow_bearer_token,
            ow_api_key=configured_ow_api_key,
            ow_timeout_seconds=selected_ow_timeout,
        )
