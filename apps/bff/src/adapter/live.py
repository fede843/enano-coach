from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

from .offline import OfflineFixtureAdapter

if TYPE_CHECKING:
    from bff.session import OwnerContext

LiveErrorCode = Literal[
    "UPSTREAM_INVALID",
    "UPSTREAM_UNAVAILABLE",
    "UPSTREAM_TIMEOUT",
    "RATE_LIMITED",
]

_ERROR_CODES = frozenset(
    {"UPSTREAM_INVALID", "UPSTREAM_UNAVAILABLE", "UPSTREAM_TIMEOUT", "RATE_LIMITED"}
)
_DEVICE_TYPES = frozenset(
    {"watch", "band", "phone", "scale", "ring", "other", "unknown"}
)
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_PAGES = 100
_SOURCE_LABEL = "Fuente conectada"
_LIVE_ERROR_MESSAGES = {
    "UPSTREAM_INVALID": "La fuente devolvi\u00f3 una respuesta no v\u00e1lida.",
    "UPSTREAM_UNAVAILABLE": "La fuente no est\u00e1 disponible; vuelve a consultar manualmente.",
    "UPSTREAM_TIMEOUT": "La fuente tard\u00f3 demasiado en responder.",
    "RATE_LIMITED": "Se alcanz\u00f3 el l\u00edmite de solicitudes.",
}

_DATA_SOURCE_FIELDS = frozenset(
    {
        "id",
        "user_id",
        "provider",
        "user_connection_id",
        "device_model",
        "software_version",
        "source",
        "device_type",
        "original_source_name",
        "display_name",
    }
)
_SOURCE_FIELDS = frozenset({"provider", "source", "device", "device_type"})
_METADATA_FIELDS = frozenset({"resolution", "sample_count", "start_time", "end_time"})
_METADATA_RESOLUTIONS = frozenset({"raw", "1min", "5min", "15min", "1hour"})
_QUERY_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~:/+=,%@-]{0,255}$")
_QUERY_RULES: dict[str, dict[str, str]] = {
    "data-sources": {},
    "summaries/activity": {
        "start_date": "datetime",
        "end_date": "datetime",
        "cursor": "cursor",
        "limit": "limit_400",
        "sort_order": "sort_order",
    },
    "summaries/sleep": {
        "start_date": "datetime",
        "end_date": "datetime",
        "cursor": "cursor",
        "limit": "limit_100",
    },
    "summaries/recovery": {
        "start_date": "datetime",
        "end_date": "datetime",
        "cursor": "cursor",
        "limit": "limit_100",
    },
    "events/sleep": {
        "start_date": "datetime",
        "end_date": "datetime",
        "filter_by_priority": "boolean",
        "cursor": "cursor",
        "limit": "limit_100",
    },
}
_REQUIRED_QUERY_KEYS = {
    "summaries/activity": frozenset({"start_date", "end_date"}),
    "summaries/sleep": frozenset({"start_date", "end_date"}),
    "summaries/recovery": frozenset({"start_date", "end_date"}),
    "events/sleep": frozenset({"start_date", "end_date"}),
}
_ACTIVITY_FIELDS = frozenset(
    {
        "date",
        "source",
        "steps",
        "distance_meters",
        "floors_climbed",
        "elevation_meters",
        "active_calories_kcal",
        "total_calories_kcal",
        "active_minutes",
        "sedentary_minutes",
        "intensity_minutes",
        "heart_rate",
    }
)
_SLEEP_SUMMARY_FIELDS = frozenset(
    {
        "date",
        "source",
        "start_time",
        "end_time",
        "duration_minutes",
        "total_duration_minutes",
        "time_in_bed_minutes",
        "efficiency_percent",
        "stages",
        "sessions",
        "nap_count",
        "nap_duration_minutes",
        "avg_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_hrv_rmssd_ms",
        "avg_respiratory_rate",
        "avg_spo2_percent",
    }
)
_SLEEP_EVENT_FIELDS = frozenset(
    {
        "id",
        "date",
        "start_time",
        "end_time",
        "duration_seconds",
        "sleep_duration_seconds",
        "is_nap",
        "source",
        "sleep_stage_intervals",
    }
)
_RECOVERY_FIELDS = frozenset(
    {
        "date",
        "source",
        "sleep_duration_seconds",
        "sleep_efficiency_percent",
        "resting_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_spo2_percent",
        "recovery_score",
    }
)
_INTENSITY_FIELDS = frozenset({"light", "moderate", "vigorous"})
_HEART_RATE_FIELDS = frozenset({"avg_bpm", "max_bpm", "min_bpm"})


class LiveOWError(Exception):
    """Safe internal error; upstream text is deliberately not retained."""

    def __init__(self, code: LiveErrorCode) -> None:
        if code not in _ERROR_CODES:
            code = "UPSTREAM_INVALID"
        self.code: LiveErrorCode = code  # type: ignore[assignment]
        super().__init__(code)


class OWResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> object: ...


class OWTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: tuple[tuple[str, str], ...],
        timeout: float,
        follow_redirects: bool,
    ) -> OWResponse: ...


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class _UrllibResponse:
    def __init__(self, response: Any) -> None:
        self.status_code = int(response.status)
        self.headers = {
            str(key).lower(): str(value) for key, value in response.headers.items()
        }
        self._response = response

    def json(self) -> object:
        body = self._response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: tuple[tuple[str, str], ...],
        timeout: float,
        follow_redirects: bool,
    ) -> OWResponse:
        if follow_redirects:
            raise ValueError("redirects are disabled")
        query = urlencode(params)
        target = f"{url}?{query}" if query else url
        request = Request(target, headers=headers, method="GET")
        try:
            response = self._opener.open(request, timeout=timeout)
        except HTTPError as error:
            return _UrllibResponse(error)
        except URLError as error:
            reason = error.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise TimeoutError from None
            raise OSError from None
        except (TimeoutError, socket.timeout):
            raise TimeoutError from None
        return _UrllibResponse(response)


def _base_url(value: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError("OW_API_BASE_URL is not valid")
    try:
        parsed = urlsplit(value)
        _ = parsed.port  # Force validation of malformed or out-of-range ports.
    except ValueError as exc:
        raise ValueError("OW_API_BASE_URL is not valid") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.hostname is None
    ):
        raise ValueError("OW_API_BASE_URL is not valid")
    if parsed.scheme.lower() == "http":
        try:
            is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname.lower() == "localhost"
        if not is_loopback:
            raise ValueError("OW_API_BASE_URL must use HTTPS outside loopback")
    return f"{parsed.scheme.lower()}://{parsed.netloc}"


def _credential(value: str, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{name} is not valid")
    return value


def _api_key(value: str) -> str:
    return _credential(value, name="OW_API_KEY")


def _bearer_token(value: str) -> str:
    return _credential(value, name="OW_BEARER_TOKEN")


def _ow_user_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("OW user reference is not a valid UUID")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError("OW user reference is not a valid UUID") from exc


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("OW_TIMEOUT_SECONDS is not valid")
    if not math.isfinite(value) or value <= 0 or value > 60:
        raise ValueError("OW_TIMEOUT_SECONDS is not valid")
    return float(value)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LiveOWError("UPSTREAM_INVALID")
    return value


def _owner_values(value: object) -> tuple[str, str, str]:
    fields = tuple(
        getattr(value, key, None)
        for key in ("principal_key", "owner_key", "ow_user_key")
    )
    if any(not isinstance(item, str) or not item for item in fields):
        raise ValueError("owner context is not valid")
    return fields  # type: ignore[return-value]


def _same_owner(left: object, right: object) -> bool:
    try:
        return _owner_values(left) == _owner_values(right)
    except ValueError:
        return False


def _fields(value: object, allowed: frozenset[str]) -> Mapping[str, Any]:
    raw = _mapping(value)
    return {key: item for key, item in raw.items() if key in allowed}


def _text(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 256:
        raise LiveOWError("UPSTREAM_INVALID")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise LiveOWError("UPSTREAM_INVALID")
    return value


def _number(
    value: object, *, optional: bool = False, nonnegative: bool = True
) -> int | float | None:
    if value is None and optional:
        return None
    if type(value) not in {int, float} or not math.isfinite(value):
        raise LiveOWError("UPSTREAM_INVALID")
    if nonnegative and value < 0:
        raise LiveOWError("UPSTREAM_INVALID")
    return value


def _date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise LiveOWError("UPSTREAM_INVALID")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise LiveOWError("UPSTREAM_INVALID") from exc
    return value


def _timestamp(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise LiveOWError("UPSTREAM_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveOWError("UPSTREAM_INVALID") from exc
    if parsed.tzinfo is None:
        raise LiveOWError("UPSTREAM_INVALID")
    return value


def _query_token(value: object) -> str:
    if not isinstance(value, str) or not _QUERY_TOKEN_PATTERN.fullmatch(value):
        raise LiveOWError("UPSTREAM_INVALID")
    return value


def _source_reference(value: object) -> tuple[str, str | None]:
    raw = _fields(value, _SOURCE_FIELDS)
    provider = _text(raw.get("provider"))
    source = _text(raw.get("source"), optional=True)
    _text(raw.get("device"), optional=True)
    device_type = _text(raw.get("device_type"), optional=True)
    if device_type is not None and device_type not in _DEVICE_TYPES:
        raise LiveOWError("UPSTREAM_INVALID")
    assert provider is not None
    return provider, source


def _source_projection(value: object) -> dict[str, Any]:
    raw = _fields(value, _SOURCE_FIELDS)
    provider = _text(raw.get("provider"))
    if provider is None:
        raise LiveOWError("UPSTREAM_INVALID")
    projection: dict[str, Any] = {"provider": provider}
    for key in ("source", "device", "device_type"):
        if key not in raw:
            continue
        item = _text(raw[key], optional=True)
        if key == "device_type" and item is not None and item not in _DEVICE_TYPES:
            raise LiveOWError("UPSTREAM_INVALID")
        projection[key] = item
    return projection


def _validate_data_source(value: object, expected_user: str) -> Mapping[str, Any]:
    raw = dict(_fields(value, _DATA_SOURCE_FIELDS))
    required = {"id", "user_id", "provider"}
    if not required.issubset(raw):
        raise LiveOWError("UPSTREAM_INVALID")
    if raw.get("user_id") != expected_user:
        raise LiveOWError("UPSTREAM_INVALID")
    _text(raw.get("id"))
    _text(raw.get("user_id"))
    _text(raw.get("provider"))
    _text(raw.get("source"), optional=True)
    device_type = _text(raw.get("device_type"), optional=True)
    if device_type is not None and device_type not in _DEVICE_TYPES:
        raise LiveOWError("UPSTREAM_INVALID")
    for key in (
        "user_connection_id",
        "device_model",
        "software_version",
        "original_source_name",
        "display_name",
    ):
        _text(raw.get(key), optional=True)
    return raw


def _validate_metadata(value: object) -> Mapping[str, Any]:
    if value is None:
        return {}
    raw = _fields(value, _METADATA_FIELDS)
    resolution = raw.get("resolution")
    if resolution is not None and (
        not isinstance(resolution, str) or resolution not in _METADATA_RESOLUTIONS
    ):
        raise LiveOWError("UPSTREAM_INVALID")
    sample_count = _number(raw.get("sample_count"), optional=True)
    if sample_count is not None and type(sample_count) is not int:
        raise LiveOWError("UPSTREAM_INVALID")
    _timestamp(raw.get("start_time"), optional=True)
    _timestamp(raw.get("end_time"), optional=True)
    return raw


def _validate_page(
    value: object,
) -> tuple[list[Mapping[str, Any]], str | None, bool, int | None]:
    raw = _mapping(value)
    if not {"data", "pagination"}.issubset(raw):
        raise LiveOWError("UPSTREAM_INVALID")
    data = raw.get("data")
    if not isinstance(data, list) or len(data) > 400:
        raise LiveOWError("UPSTREAM_INVALID")
    if "metadata" in raw:
        _validate_metadata(raw["metadata"])
    pagination = _fields(
        raw.get("pagination"),
        frozenset({"next_cursor", "previous_cursor", "has_more", "total_count"}),
    )
    if "has_more" not in pagination:
        raise LiveOWError("UPSTREAM_INVALID")
    next_cursor = _text(pagination.get("next_cursor"), optional=True)
    _text(pagination.get("previous_cursor"), optional=True)
    has_more = pagination.get("has_more")
    if type(has_more) is not bool:
        raise LiveOWError("UPSTREAM_INVALID")
    total_count = _number(pagination.get("total_count"), optional=True)
    if total_count is not None and type(total_count) is not int:
        raise LiveOWError("UPSTREAM_INVALID")
    if has_more != (next_cursor is not None):
        raise LiveOWError("UPSTREAM_INVALID")
    return (
        [_mapping(item) for item in data],
        next_cursor,
        has_more,
        total_count,
    )  # type: ignore[return-value]


class LiveOWClient:
    """Small allowlisted, read-only OW HTTP client for local live-read tests."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        bearer_token: str | None = None,
        expected_owner_context: OwnerContext,
        timeout_seconds: float = 10.0,
        transport: OWTransport | None = None,
    ) -> None:
        _owner_values(expected_owner_context)
        self._base_url = _base_url(base_url)
        self._ow_user_key = _ow_user_uuid(expected_owner_context.ow_user_key)
        if bearer_token is not None:
            self._auth_header = (
                "Authorization",
                f"Bearer {_bearer_token(bearer_token)}",
            )
        elif api_key is not None:
            self._auth_header = (
                "X-Open-Wearables-API-Key",
                _api_key(api_key),
            )
        else:
            raise ValueError("OW_BEARER_TOKEN or OW_API_KEY is required")
        self._expected_owner_context = expected_owner_context
        self._timeout_seconds = _timeout(timeout_seconds)
        self._transport = transport or _UrllibTransport()

    def __repr__(self) -> str:
        return "LiveOWClient(base_url={!r}, timeout_seconds={!r})".format(
            self._base_url, self._timeout_seconds
        )

    def _user_path(self, suffix: str) -> str:
        return f"/api/v1/users/{quote(self._ow_user_key, safe='-._~')}/{suffix}"

    def _assert_owner(self, owner_context: OwnerContext) -> None:
        if not _same_owner(owner_context, self._expected_owner_context):
            raise LiveOWError("UPSTREAM_INVALID")

    def _allowed_paths(self) -> frozenset[str]:
        return frozenset(
            {
                self._user_path("data-sources"),
                self._user_path("summaries/activity"),
                self._user_path("summaries/sleep"),
                self._user_path("summaries/recovery"),
                self._user_path("events/sleep"),
            }
        )

    def _validate_query_params(
        self,
        relative_path: str,
        params: Sequence[tuple[str, str]],
    ) -> tuple[tuple[str, str], ...]:
        prefix = self._user_path("")
        suffix = (
            relative_path[len(prefix) :] if relative_path.startswith(prefix) else ""
        )
        rules = _QUERY_RULES.get(suffix)
        if rules is None:
            raise LiveOWError("UPSTREAM_INVALID")
        try:
            pairs = tuple(params)
        except (TypeError, ValueError):
            raise LiveOWError("UPSTREAM_INVALID") from None

        validated: list[tuple[str, str]] = []
        seen: set[str] = set()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise LiveOWError("UPSTREAM_INVALID")
            key, value = pair
            if not isinstance(key, str) or not isinstance(value, str) or key in seen:
                raise LiveOWError("UPSTREAM_INVALID")
            rule = rules.get(key)
            if rule is None or not value:
                raise LiveOWError("UPSTREAM_INVALID")
            if rule == "datetime":
                _timestamp(value)
            elif rule == "cursor":
                _query_token(value)
            elif rule == "boolean":
                if value not in {"true", "false"}:
                    raise LiveOWError("UPSTREAM_INVALID")
            elif rule == "sort_order":
                if value not in {"asc", "desc"}:
                    raise LiveOWError("UPSTREAM_INVALID")
            elif rule in {"limit_100", "limit_400"}:
                maximum = 100 if rule == "limit_100" else 400
                if (
                    not re.fullmatch(r"[0-9]{1,3}", value)
                    or not 1 <= int(value) <= maximum
                ):
                    raise LiveOWError("UPSTREAM_INVALID")
            else:
                raise LiveOWError("UPSTREAM_INVALID")
            seen.add(key)
            validated.append((key, value))
        required = _REQUIRED_QUERY_KEYS.get(suffix, frozenset())
        if not required.issubset(seen):
            raise LiveOWError("UPSTREAM_INVALID")
        return tuple(validated)

    def request_json(
        self,
        *,
        owner_context: OwnerContext,
        relative_path: str,
        params: Sequence[tuple[str, str]],
    ) -> Mapping[str, Any]:
        self._assert_owner(owner_context)
        if relative_path not in self._allowed_paths():
            raise LiveOWError("UPSTREAM_INVALID")
        params = self._validate_query_params(relative_path, params)
        try:
            response = self._transport.get(
                f"{self._base_url}{relative_path}",
                headers={
                    "Accept": "application/json",
                    self._auth_header[0]: self._auth_header[1],
                },
                params=tuple(params),
                timeout=self._timeout_seconds,
                follow_redirects=False,
            )
        except LiveOWError:
            raise
        except TimeoutError:
            raise LiveOWError("UPSTREAM_TIMEOUT") from None
        except (OSError, RuntimeError, ValueError):
            raise LiveOWError("UPSTREAM_UNAVAILABLE") from None
        except Exception:
            raise LiveOWError("UPSTREAM_UNAVAILABLE") from None

        status_code = response.status_code
        if type(status_code) is not int:
            raise LiveOWError("UPSTREAM_INVALID")
        if status_code != 200:
            if status_code == 408:
                raise LiveOWError("UPSTREAM_TIMEOUT")
            if status_code == 429:
                raise LiveOWError("RATE_LIMITED")
            if 500 <= status_code <= 599:
                raise LiveOWError("UPSTREAM_UNAVAILABLE")
            raise LiveOWError("UPSTREAM_INVALID")
        content_type = response.headers.get("content-type") or response.headers.get(
            "Content-Type"
        )
        if content_type is not None and "json" not in content_type.lower():
            raise LiveOWError("UPSTREAM_INVALID")
        try:
            payload = response.json()
        except Exception:
            raise LiveOWError("UPSTREAM_INVALID") from None
        return deepcopy(_mapping(payload))

    def get_data_sources(
        self, *, owner_context: OwnerContext
    ) -> list[Mapping[str, Any]]:
        response = self.request_json(
            owner_context=owner_context,
            relative_path=self._user_path("data-sources"),
            params=(),
        )
        raw = _fields(response, frozenset({"items", "total"}))
        if set(raw) != {"items", "total"}:
            raise LiveOWError("UPSTREAM_INVALID")
        items = raw.get("items")
        total = raw.get("total")
        if not isinstance(items, list) or len(items) > 100:
            raise LiveOWError("UPSTREAM_INVALID")
        if type(total) is not int or total < 0:
            raise LiveOWError("UPSTREAM_INVALID")
        return [_validate_data_source(item, self._ow_user_key) for item in items]

    def get_paginated(
        self,
        *,
        owner_context: OwnerContext,
        relative_path: str,
        params: Sequence[tuple[str, str]],
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(_MAX_PAGES):
            page_params = tuple(params)
            if cursor is not None:
                page_params += (("cursor", cursor),)
            response = self.request_json(
                owner_context=owner_context,
                relative_path=relative_path,
                params=page_params,
            )
            page_rows, next_cursor, has_more, _total_count = _validate_page(response)
            validators = {
                self._user_path("summaries/activity"): _validate_activity,
                self._user_path("summaries/sleep"): _validate_sleep_summary,
                self._user_path("events/sleep"): _validate_sleep_event,
                self._user_path("summaries/recovery"): _validate_recovery,
            }
            validator = validators.get(relative_path)
            if validator is None:
                raise LiveOWError("UPSTREAM_INVALID")
            rows.extend(validator(row) for row in page_rows)
            if not has_more:
                return rows
            if next_cursor is None or next_cursor in seen_cursors:
                raise LiveOWError("UPSTREAM_INVALID")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise LiveOWError("UPSTREAM_INVALID")

    def get_activity_summary(
        self,
        *,
        owner_context: OwnerContext,
        start_date: str,
        end_date: str,
    ) -> list[Mapping[str, Any]]:
        return self.get_paginated(
            owner_context=owner_context,
            relative_path=self._user_path("summaries/activity"),
            params=(
                ("start_date", start_date),
                ("end_date", end_date),
                ("limit", "400"),
            ),
        )

    def get_sleep_summary(
        self,
        *,
        owner_context: OwnerContext,
        start_date: str,
        end_date: str,
    ) -> list[Mapping[str, Any]]:
        return self.get_paginated(
            owner_context=owner_context,
            relative_path=self._user_path("summaries/sleep"),
            params=(
                ("start_date", start_date),
                ("end_date", end_date),
                ("limit", "100"),
            ),
        )

    def get_sleep_events(
        self,
        *,
        owner_context: OwnerContext,
        start_date: str,
        end_date: str,
    ) -> list[Mapping[str, Any]]:
        return self.get_paginated(
            owner_context=owner_context,
            relative_path=self._user_path("events/sleep"),
            params=(
                ("start_date", start_date),
                ("end_date", end_date),
                ("limit", "100"),
            ),
        )

    def get_recovery_summary(
        self,
        *,
        owner_context: OwnerContext,
        start_date: str,
        end_date: str,
    ) -> list[Mapping[str, Any]]:
        return self.get_paginated(
            owner_context=owner_context,
            relative_path=self._user_path("summaries/recovery"),
            params=(
                ("start_date", start_date),
                ("end_date", end_date),
                ("limit", "100"),
            ),
        )


SourceIdentity = tuple[str, str | None]


def _source_identity(value: object) -> SourceIdentity:
    return _source_reference(value)


def _record_source_identity(value: Mapping[str, Any]) -> SourceIdentity:
    provider = _text(value.get("provider"))
    source = _text(value.get("source"), optional=True)
    assert provider is not None
    return provider, source


def _validate_activity(value: object) -> Mapping[str, Any]:
    raw = dict(_fields(value, _ACTIVITY_FIELDS))
    if "date" not in raw or "source" not in raw:
        raise LiveOWError("UPSTREAM_INVALID")
    _date(raw["date"])
    _source_reference(raw["source"])
    raw["source"] = _source_projection(raw["source"])
    for key in (
        "steps",
        "distance_meters",
        "floors_climbed",
        "elevation_meters",
        "active_calories_kcal",
        "total_calories_kcal",
        "active_minutes",
        "sedentary_minutes",
    ):
        if key in raw:
            _number(raw[key], optional=True)
    if "intensity_minutes" in raw:
        if raw["intensity_minutes"] is None:
            intensity = None
        else:
            intensity = dict(_fields(raw["intensity_minutes"], _INTENSITY_FIELDS))
        if intensity is not None:
            for key in intensity:
                _number(intensity[key], optional=True)
            raw["intensity_minutes"] = intensity
    if "heart_rate" in raw:
        if raw["heart_rate"] is None:
            heart_rate = None
        else:
            heart_rate = dict(_fields(raw["heart_rate"], _HEART_RATE_FIELDS))
        if heart_rate is not None:
            for key in heart_rate:
                _number(heart_rate[key], optional=True)
            raw["heart_rate"] = heart_rate
    return raw


def _validate_sleep_summary(value: object) -> Mapping[str, Any]:
    raw = dict(_fields(value, _SLEEP_SUMMARY_FIELDS))
    if "date" not in raw or "source" not in raw:
        raise LiveOWError("UPSTREAM_INVALID")
    _date(raw["date"])
    _source_reference(raw["source"])
    raw["source"] = _source_projection(raw["source"])
    for key in ("start_time", "end_time"):
        if key in raw:
            _timestamp(raw[key], optional=True)
    for key in (
        "duration_minutes",
        "total_duration_minutes",
        "time_in_bed_minutes",
        "efficiency_percent",
        "nap_count",
        "nap_duration_minutes",
        "avg_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_hrv_rmssd_ms",
        "avg_respiratory_rate",
        "avg_spo2_percent",
    ):
        if key in raw:
            _number(raw[key], optional=True)
    if "sessions" in raw and raw["sessions"] is not None:
        if not isinstance(raw["sessions"], list):
            raise LiveOWError("UPSTREAM_INVALID")
        raw["sessions"] = [
            dict(
                _fields(
                    session,
                    frozenset(
                        {
                            "start_time",
                            "end_time",
                            "zone_offset",
                            "duration_minutes",
                            "is_nap",
                        }
                    ),
                )
            )
            for session in raw["sessions"]
        ]
    if "stages" in raw and raw["stages"] is not None:
        stages = dict(
            _fields(
                raw["stages"],
                frozenset(
                    {"awake_minutes", "light_minutes", "deep_minutes", "rem_minutes"}
                ),
            )
        )
        for value in stages.values():
            _number(value, optional=True)
        raw["stages"] = stages
    return raw


def _validate_sleep_event(value: object) -> Mapping[str, Any]:
    raw = dict(_fields(value, _SLEEP_EVENT_FIELDS))
    required = {"id", "start_time", "end_time", "is_nap", "source"}
    if not required.issubset(raw):
        raise LiveOWError("UPSTREAM_INVALID")
    _text(raw["id"])
    if "date" in raw:
        _date(raw["date"])
    _timestamp(raw["start_time"])
    _timestamp(raw["end_time"])
    if type(raw["is_nap"]) is not bool:
        raise LiveOWError("UPSTREAM_INVALID")
    _source_reference(raw["source"])
    raw["source"] = _source_projection(raw["source"])
    for key in ("duration_seconds", "sleep_duration_seconds"):
        if key in raw:
            _number(raw[key], optional=True)
    intervals = raw.get("sleep_stage_intervals")
    if intervals is not None:
        if not isinstance(intervals, list):
            raise LiveOWError("UPSTREAM_INVALID")
        sanitized_intervals: list[dict[str, Any]] = []
        for interval in intervals:
            interval_raw = dict(
                _fields(interval, frozenset({"start_time", "end_time", "stage"}))
            )
            if set(interval_raw) != {"start_time", "end_time", "stage"}:
                raise LiveOWError("UPSTREAM_INVALID")
            _timestamp(interval_raw["start_time"])
            _timestamp(interval_raw["end_time"])
            stage = _text(interval_raw["stage"])
            if stage not in {
                "in_bed",
                "awake",
                "sleeping",
                "light",
                "deep",
                "rem",
                "unknown",
            }:
                raise LiveOWError("UPSTREAM_INVALID")
            sanitized_intervals.append(interval_raw)
        raw["sleep_stage_intervals"] = sanitized_intervals
    return raw


def _validate_recovery(value: object) -> Mapping[str, Any]:
    raw = dict(_fields(value, _RECOVERY_FIELDS))
    if "date" not in raw or "source" not in raw:
        raise LiveOWError("UPSTREAM_INVALID")
    _date(raw["date"])
    _source_reference(raw["source"])
    raw["source"] = _source_projection(raw["source"])
    for key in (
        "sleep_duration_seconds",
        "sleep_efficiency_percent",
        "resting_heart_rate_bpm",
        "avg_hrv_sdnn_ms",
        "avg_spo2_percent",
        "recovery_score",
    ):
        if key in raw:
            _number(raw[key], optional=True)
    score = raw.get("recovery_score")
    if score is not None and (type(score) is not int or not 0 <= score <= 100):
        raise LiveOWError("UPSTREAM_INVALID")
    return raw


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _error_response(code: LiveErrorCode, timezone_name: str) -> dict[str, Any]:
    public_code = code if code in _ERROR_CODES else "UPSTREAM_INVALID"
    return {
        "schemaVersion": "1",
        "asOf": _now(),
        "timezone": timezone_name if isinstance(timezone_name, str) else "UTC",
        "data": None,
        "coverage": {},
        "warnings": [],
        "extensions": {},
        "error": {
            "code": public_code,
            "message": _LIVE_ERROR_MESSAGES[public_code],
            "requestId": "req-demo-live",
            "retryable": public_code in {"UPSTREAM_UNAVAILABLE", "UPSTREAM_TIMEOUT"},
            "field": None,
        },
    }


def _warning(*, domain: str | None = None) -> dict[str, str]:
    warning = {
        "code": "SOURCE_AMBIGUOUS",
        "severity": "warning",
        "message": "La atribución requiere una regla adicional.",
    }
    if domain is not None:
        warning["domain"] = domain
    return warning


class LiveOWAdapter:
    """Live read adapter with fixture fallback for non-health control routes."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        bearer_token: str | None = None,
        expected_owner_context: OwnerContext,
        timeout_seconds: float = 10.0,
        transport: OWTransport | None = None,
        fallback: OfflineFixtureAdapter | None = None,
    ) -> None:
        self._client = LiveOWClient(
            base_url=base_url,
            api_key=api_key,
            bearer_token=bearer_token,
            expected_owner_context=expected_owner_context,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self._fallback = fallback or OfflineFixtureAdapter()
        self._aliases: dict[str, dict[SourceIdentity, str]] = {}

    def __repr__(self) -> str:
        return "LiveOWAdapter(client={!r})".format(self._client)

    def get_bff_response(
        self, case: str, *, owner_context: OwnerContext
    ) -> dict[str, Any]:
        self._client._assert_owner(owner_context)
        return self._fallback.get_bff_response(case)

    def _source_aliases(
        self, owner_context: OwnerContext, records: Sequence[Mapping[str, Any]]
    ) -> dict[SourceIdentity, str]:
        owner_aliases = self._aliases.setdefault(owner_context.owner_key, {})
        for record in records:
            identity = _record_source_identity(record)
            if identity not in owner_aliases:
                next_number = len(owner_aliases) + 1
                if next_number > 99:
                    raise LiveOWError("UPSTREAM_INVALID")
                owner_aliases[identity] = f"source-live-{next_number:02d}"
        return owner_aliases

    @staticmethod
    def _source_items(
        records: Sequence[Mapping[str, Any]],
        aliases: Mapping[SourceIdentity, str],
        capabilities: Mapping[SourceIdentity, set[str]],
    ) -> list[dict[str, Any]]:
        identities = list(
            dict.fromkeys(_record_source_identity(record) for record in records)
        )
        ambiguous = len(identities) > 1
        return [
            {
                "sourceKey": aliases[identity],
                "label": _SOURCE_LABEL,
                "state": "source_ambiguous" if ambiguous else "ready",
                "capabilities": sorted(capabilities.get(identity, set())),
            }
            for identity in identities
        ]

    @staticmethod
    def _metric(
        value: object,
        *,
        unit: str | None,
        is_daily_total: bool,
        identity: SourceIdentity | None,
        aliases: Mapping[SourceIdentity, str],
        ambiguous: bool,
        metric_name: str,
    ) -> dict[str, Any]:
        numeric = _number(value, optional=True)
        if numeric is None:
            return {
                "state": "null",
                "value": None,
                "unit": None,
                "isDailyTotal": is_daily_total,
            }
        if numeric == 0:
            if not is_daily_total and unit is not None:
                raise LiveOWError("UPSTREAM_INVALID")
            return {
                "state": "zero",
                "value": 0,
                "unit": unit,
                "isDailyTotal": is_daily_total,
            }
        state = "source_ambiguous" if ambiguous or identity not in aliases else "value"
        result: dict[str, Any] = {
            "state": state,
            "value": numeric,
            "unit": unit,
            "isDailyTotal": is_daily_total,
        }
        if state == "value" and identity is not None:
            result["sourceKey"] = aliases[identity]
        del metric_name
        return result

    @staticmethod
    def _heart_rate(
        value: object,
        *,
        identity: SourceIdentity | None,
        aliases: Mapping[SourceIdentity, str],
        ambiguous: bool,
    ) -> dict[str, Any]:
        numeric = _number(value, optional=True)
        if numeric is None:
            return {
                "state": "null",
                "value": None,
                "unit": None,
                "isDailyTotal": False,
            }
        if numeric <= 0:
            raise LiveOWError("UPSTREAM_INVALID")
        state = "source_ambiguous" if ambiguous or identity not in aliases else "value"
        return {
            "state": state,
            "value": numeric,
            "unit": "bpm",
            "isDailyTotal": False,
        }

    def get_overview_response(
        self,
        *,
        logical_date: str,
        timezone_name: str,
        from_utc: str,
        to_utc: str,
        owner_context: OwnerContext,
    ) -> dict[str, Any]:
        try:
            _date(logical_date)
            source_records = self._client.get_data_sources(owner_context=owner_context)
            aliases = self._source_aliases(owner_context, source_records)
            activity = [
                _validate_activity(record)
                for record in self._client.get_activity_summary(
                    owner_context=owner_context,
                    start_date=from_utc,
                    end_date=to_utc,
                )
                if _date(record.get("date")) == logical_date
            ]
            sleep_summary = [
                _validate_sleep_summary(record)
                for record in self._client.get_sleep_summary(
                    owner_context=owner_context,
                    start_date=from_utc,
                    end_date=to_utc,
                )
                if _date(record.get("date")) == logical_date
            ]
            sleep_events = [
                _validate_sleep_event(record)
                for record in self._client.get_sleep_events(
                    owner_context=owner_context,
                    start_date=from_utc,
                    end_date=to_utc,
                )
                if (
                    _date(record["date"])
                    if "date" in record
                    else datetime.fromisoformat(
                        str(record["end_time"]).replace("Z", "+00:00")
                    ).astimezone(ZoneInfo(timezone_name)).date().isoformat()
                )
                == logical_date
                and record.get("is_nap") is False
            ]
            recovery = [
                _validate_recovery(record)
                for record in self._client.get_recovery_summary(
                    owner_context=owner_context,
                    start_date=from_utc,
                    end_date=to_utc,
                )
                if _date(record.get("date")) == logical_date
            ]
            capabilities: dict[SourceIdentity, set[str]] = {}
            for record in activity:
                identity = _source_identity(record["source"])
                capabilities.setdefault(identity, set()).add("activity")
                if (
                    isinstance(record.get("heart_rate"), Mapping)
                    and record["heart_rate"].get("avg_bpm") is not None
                ):
                    capabilities[identity].add("heart_rate")
            for record in sleep_summary + sleep_events:
                capabilities.setdefault(_source_identity(record["source"]), set()).add(
                    "sleep"
                )
            for record in recovery:
                capabilities.setdefault(_source_identity(record["source"]), set()).add(
                    "body"
                )
            source_items = self._source_items(source_records, aliases, capabilities)
            ambiguous = (
                len({_record_source_identity(record) for record in source_records}) > 1
            )
            summary: dict[str, Any] = {}
            if activity:
                row = activity[0]
                identity = _source_identity(row["source"])
                summary_fields = (
                    ("steps", "steps", "count"),
                    ("distanceMeters", "distance_meters", "meters"),
                    ("activeCaloriesKcal", "active_calories_kcal", "kcal"),
                )
                for output_name, input_name, unit in summary_fields:
                    if input_name in row:
                        summary[output_name] = self._metric(
                            row[input_name],
                            unit=unit,
                            is_daily_total=True,
                            identity=identity,
                            aliases=aliases,
                            ambiguous=ambiguous,
                            metric_name=output_name,
                        )
                heart_rate = row.get("heart_rate")
                if isinstance(heart_rate, Mapping) and "avg_bpm" in heart_rate:
                    summary["heartRate"] = self._heart_rate(
                        heart_rate["avg_bpm"],
                        identity=identity,
                        aliases=aliases,
                        ambiguous=ambiguous,
                    )
            if sleep_events:
                event = sleep_events[0]
                summary["sleepDurationSeconds"] = self._metric(
                    event.get("sleep_duration_seconds"),
                    unit="seconds",
                    is_daily_total=False,
                    identity=_source_identity(event["source"]),
                    aliases=aliases,
                    ambiguous=ambiguous,
                    metric_name="sleepDurationSeconds",
                )
            elif sleep_summary:
                summary["sleepDurationSeconds"] = {
                    "state": "null",
                    "value": None,
                    "unit": None,
                    "isDailyTotal": False,
                }
            if recovery:
                record = recovery[0]
                summary["recoveryScore"] = self._metric(
                    record.get("recovery_score"),
                    unit=None,
                    is_daily_total=False,
                    identity=_source_identity(record["source"]),
                    aliases=aliases,
                    ambiguous=ambiguous,
                    metric_name="recoveryScore",
                )
            summary["stress"] = {
                "state": "unsupported",
                "value": None,
                "unit": None,
                "isDailyTotal": None,
            }
            available = (
                1 if activity or sleep_summary or sleep_events or recovery else 0
            )
            by_domain: dict[str, dict[str, Any]] = {}
            if activity:
                by_domain["activity"] = {
                    "expectedDays": 1,
                    "availableDays": 1,
                    "state": "complete",
                }
            if sleep_summary or sleep_events:
                by_domain["sleep"] = {
                    "expectedDays": 1,
                    "availableDays": 1,
                    "state": "complete",
                }
            if recovery:
                by_domain["recovery"] = {
                    "expectedDays": 1,
                    "availableDays": 1,
                    "state": "complete",
                }
            ambiguous_domains = {
                domain
                for metric_name, domain in (
                    ("steps", "activity"),
                    ("distanceMeters", "activity"),
                    ("activeCaloriesKcal", "activity"),
                    ("sleepDurationSeconds", "sleep"),
                    ("recoveryScore", "recovery"),
                    ("heartRate", "heart_rate"),
                )
                if summary.get(metric_name, {}).get("state") == "source_ambiguous"
            }
            warnings = (
                [_warning(domain=domain) for domain in sorted(ambiguous_domains)]
                if ambiguous_domains
                else ([_warning()] if ambiguous else [])
            )
            return {
                "schemaVersion": "1",
                "asOf": _now(),
                "timezone": timezone_name,
                "data": {
                    "logicalDate": logical_date,
                    "summary": summary,
                    "sources": source_items,
                },
                "coverage": {
                    "requested": {
                        "logicalDate": logical_date,
                        "from": from_utc,
                        "to": to_utc,
                        "timezone": timezone_name,
                    },
                    "expectedDays": 1,
                    "availableDays": available,
                    "isPartial": False,
                    "byDomain": by_domain,
                },
                "warnings": warnings,
                "extensions": {},
            }
        except LiveOWError as error:
            return _error_response(error.code, timezone_name)
        except (KeyError, TypeError, ValueError):
            return _error_response("UPSTREAM_INVALID", timezone_name)

    def get_sources_response(
        self,
        *,
        logical_date: str,
        timezone_name: str,
        owner_context: OwnerContext,
    ) -> dict[str, Any]:
        del logical_date
        try:
            records = self._client.get_data_sources(owner_context=owner_context)
            aliases = self._source_aliases(owner_context, records)
            identities = {_record_source_identity(record) for record in records}
            capabilities = {identity: set() for identity in identities}
            return {
                "schemaVersion": "1",
                "asOf": _now(),
                "timezone": timezone_name,
                "data": {"items": self._source_items(records, aliases, capabilities)},
                "coverage": {},
                "warnings": [_warning()] if len(identities) > 1 else [],
                "extensions": {},
            }
        except LiveOWError as error:
            return _error_response(error.code, timezone_name)
        except (KeyError, TypeError, ValueError):
            return _error_response("UPSTREAM_INVALID", timezone_name)


__all__ = ["LiveOWAdapter", "LiveOWClient", "LiveOWError", "OWTransport"]
