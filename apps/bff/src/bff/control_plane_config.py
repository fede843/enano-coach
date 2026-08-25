"""Feature-gated configuration for the separate application database.

The FastAPI app does not consume this setting yet.  It exists so a later
database wave has one server-side configuration boundary rather than accepting
a URL from a request or reusing an Open Wearables database setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import IPv4Address, ip_address
from os import environ
from typing import Mapping

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

CONTROL_PLANE_ENABLED_ENV = "BFF_CONTROL_PLANE_ENABLED"
APP_DATABASE_URL_ENV = "APP_DATABASE_URL"
OW_DATABASE_URL_ENV = "OW_DATABASE_URL"
_POSTGRES_BACKEND = "postgresql"
_SUPPORTED_APP_POSTGRES_DRIVERS = frozenset({"postgresql+psycopg"})
_POSTGRES_MIN_PORT = 1
_POSTGRES_MAX_PORT = 65535
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_LEGACY_IPV4_DIGITS = frozenset("0123456789.")
_LEGACY_IPV4_HEX_PREFIXES = frozenset({"0x", "0X"})
_LEGACY_IPV4_NUMERIC_PREFIXES = _LEGACY_IPV4_HEX_PREFIXES | frozenset({"0o", "0O"})
_ALLOWED_POSTGRES_QUERY_OPTIONS = frozenset(
    {"application_name", "connect_timeout", "sslmode"}
)
_TARGET_QUERY_OPTIONS = frozenset(
    {
        "dbname",
        "database",
        "db",
        "db_name",
        "database_name",
        "host",
        "hostaddr",
        "port",
        "service",
        "user",
        "username",
        "server",
        "server_name",
        "endpoint",
        "instance",
        "instance_name",
        "dsn",
        "url",
        "connection_string",
        "connectionstring",
        "target_session_attrs",
        "load_balance_hosts",
        "replication",
    }
)


def _parse_enabled(value: str | None) -> bool:
    normalized = "false" if value is None else value.strip().casefold()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"{CONTROL_PLANE_ENABLED_ENV} must be a boolean")


def _validate_app_database_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value
    _parse_postgresql_url(
        url,
        env_name=APP_DATABASE_URL_ENV,
        require_supported_driver=True,
    )
    return url


def _parse_postgresql_url(
    value: str, *, env_name: str, require_supported_driver: bool = False
) -> URL:
    """Parse a PostgreSQL URL without exposing its credential components."""

    try:
        url = make_url(value)
        if any(
            "@" in component
            for component in (url.username, url.password, url.host)
            if component is not None
        ):
            raise ValueError
        driver = url.drivername.casefold()
        if driver.split("+", 1)[0] != _POSTGRES_BACKEND:
            raise ValueError
        if (
            require_supported_driver
            and url.drivername not in _SUPPORTED_APP_POSTGRES_DRIVERS
        ):
            raise ValueError
        _canonical_postgresql_host(url, value)
        port = url.port
    except (ArgumentError, TypeError, UnicodeError, ValueError):
        raise ValueError(f"{env_name} must use PostgreSQL") from None
    _validate_database_name(url.database, env_name=env_name)
    query_options = {key.casefold() for key in url.query}
    if query_options & _TARGET_QUERY_OPTIONS or not query_options <= (
        _ALLOWED_POSTGRES_QUERY_OPTIONS
    ):
        raise ValueError(f"{env_name} contains unsupported connection options")
    try:
        if port is None or not _POSTGRES_MIN_PORT <= port <= _POSTGRES_MAX_PORT:
            raise ValueError
    except (UnicodeError, ValueError):
        raise ValueError(f"{env_name} must use PostgreSQL") from None
    return url


def _validate_database_name(database: str | None, *, env_name: str) -> str:
    if database is None or not database or database.isspace():
        raise ValueError(f"{env_name} must include a database")
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F or character in {"/", "\\"}
        for character in database
    ):
        raise ValueError(f"{env_name} must include a valid database name")
    return database


def _looks_like_legacy_ipv4(hostname: str) -> bool:
    if all(character in _LEGACY_IPV4_DIGITS for character in hostname):
        return True
    return any(
        component.startswith(tuple(_LEGACY_IPV4_NUMERIC_PREFIXES))
        for component in hostname.split(".")
    )


def _parse_legacy_ipv4_component(component: str) -> int:
    if component.startswith(tuple(_LEGACY_IPV4_HEX_PREFIXES)):
        digits = component[2:]
        base = 16
        allowed_digits = "0123456789abcdefABCDEF"
    elif len(component) > 1 and component.startswith("0"):
        digits = component[1:]
        base = 8
        allowed_digits = "01234567"
    else:
        digits = component
        base = 10
        allowed_digits = "0123456789"

    if not digits or any(character not in allowed_digits for character in digits):
        raise ValueError
    return int(digits, base)


def _canonical_legacy_ipv4(hostname: str) -> IPv4Address | None:
    """Parse legacy numeric IPv4 forms without consulting a resolver."""

    if not _looks_like_legacy_ipv4(hostname):
        return None

    components = hostname.split(".")
    if not 1 <= len(components) <= 4 or any(not component for component in components):
        raise ValueError
    values = [_parse_legacy_ipv4_component(component) for component in components]

    if len(values) == 1:
        if values[0] > 0xFFFFFFFF:
            raise ValueError
        address = values[0]
    elif len(values) == 2:
        if values[0] > 0xFF or values[1] > 0xFFFFFF:
            raise ValueError
        address = (values[0] << 24) | values[1]
    elif len(values) == 3:
        if values[0] > 0xFF or values[1] > 0xFF or values[2] > 0xFFFF:
            raise ValueError
        address = (values[0] << 24) | (values[1] << 16) | values[2]
    else:
        if any(value > 0xFF for value in values):
            raise ValueError
        address = (values[0] << 24) | (values[1] << 16) | (values[2] << 8) | values[3]
    return IPv4Address(address)


def _authority_host_text(value: str) -> str:
    """Extract only the raw host text after SQLAlchemy has parsed the URL."""

    scheme_separator = value.find("://")
    if scheme_separator < 0:
        raise ValueError
    authority = value[scheme_separator + 3 :].split("/", 1)[0].split("?", 1)[0]
    if not authority:
        raise ValueError
    return authority.rpartition("@")[2]


def _canonical_postgresql_host(url: URL, value: str) -> str:
    """Return a single canonical host from SQLAlchemy's validated URL."""

    hostname = url.host
    if not hostname:
        raise ValueError

    # SQLAlchemy normalizes away IPv6 brackets, so retain only that raw syntax
    # bit here; make_url remains the sole URL parser.
    authority = _authority_host_text(value)
    bracketed = authority.startswith("[")
    if bracketed:
        closing_bracket = authority.find("]")
        port_suffix = authority[closing_bracket + 1 :] if closing_bracket >= 0 else ""
        if (
            closing_bracket <= 1
            or "]" in port_suffix
            or not port_suffix.startswith(":")
            or not port_suffix[1:]
            or not all("0" <= character <= "9" for character in port_suffix[1:])
            or ":" not in hostname
        ):
            raise ValueError
    elif ":" in hostname or "[" in authority or "]" in authority:
        raise ValueError

    if any(
        character.isspace()
        or ord(character) < 0x20
        or character in {",", "/", "\\", "%", "[", "]", "?", "#", "@"}
        for character in hostname
    ):
        raise ValueError

    if hostname.endswith("."):
        hostname = hostname[:-1]
    if not hostname:
        raise ValueError

    try:
        address = ip_address(hostname)
    except ValueError:
        address = _canonical_legacy_ipv4(hostname)
        if address is not None:
            if bracketed:
                raise ValueError from None
        elif bracketed or ":" in hostname:
            raise ValueError from None
        else:
            normalized = hostname.casefold()
            if (
                not normalized.isascii()
                or normalized.startswith(".")
                or normalized.endswith(".")
                or ".." in normalized
                or any(
                    not (character.isalnum() or character in {".", "_", "-"})
                    for character in normalized
                )
            ):
                raise ValueError from None
            labels = normalized.split(".")
            if any(
                not label or label.startswith("-") or label.endswith("-")
                for label in labels
            ):
                raise ValueError from None
            return normalized

    if bracketed != (address.version == 6):
        raise ValueError
    # IPv4-mapped IPv6 literals identify the same safe numeric address.
    mapped_address = getattr(address, "ipv4_mapped", None)
    return str(mapped_address or address)


def _database_url_identity(value: str, *, env_name: str) -> tuple[str, int, str]:
    """Return the physical PostgreSQL target without credentials or options."""

    url = _parse_postgresql_url(
        value,
        env_name=env_name,
        require_supported_driver=env_name == APP_DATABASE_URL_ENV,
    )
    try:
        port = url.port
        if port is None:
            raise ValueError
        host = _canonical_postgresql_host(url, value)
    except (UnicodeError, ValueError):
        raise ValueError(f"{env_name} must use PostgreSQL") from None

    database = _validate_database_name(url.database, env_name=env_name)
    return host, port, database


def _reject_database_reuse(
    app_database_url: str | None, ow_database_url: str | None
) -> None:
    if (
        app_database_url is not None
        and ow_database_url is not None
        and _database_url_identity(app_database_url, env_name=APP_DATABASE_URL_ENV)
        == _database_url_identity(ow_database_url, env_name=OW_DATABASE_URL_ENV)
    ):
        raise ValueError("APP_DATABASE_URL must be separate from OW_DATABASE_URL")


@dataclass(frozen=True)
class ControlPlaneSettings:
    """Server-only feature gate and URL for the owned application database."""

    enabled: bool
    app_database_url: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(
        cls, values: Mapping[str, str] | None = None
    ) -> ControlPlaneSettings:
        source = environ if values is None else values
        enabled = _parse_enabled(source.get(CONTROL_PLANE_ENABLED_ENV))
        app_database_url = _validate_app_database_url(source.get(APP_DATABASE_URL_ENV))
        ow_database_url = source.get(OW_DATABASE_URL_ENV)
        if ow_database_url is not None:
            ow_database_url = ow_database_url if ow_database_url.strip() else None
        _reject_database_reuse(app_database_url, ow_database_url)
        if enabled and app_database_url is None:
            raise ValueError(
                f"{APP_DATABASE_URL_ENV} is required when control plane is enabled"
            )
        return cls(enabled=enabled, app_database_url=app_database_url)


__all__ = [
    "APP_DATABASE_URL_ENV",
    "CONTROL_PLANE_ENABLED_ENV",
    "ControlPlaneSettings",
    "OW_DATABASE_URL_ENV",
]
