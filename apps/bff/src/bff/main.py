from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import Mapping
from itertools import count
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from adapter.live import LiveOWAdapter
from adapter.offline import load_offline_fixture_adapter

from .config import Settings
from .errors import BFFError, error_for
from .models import CreateRunBody, ErrorBody
from .serializers import serialize_error
from .service import BFFService, validate_date, validate_timezone
from .session import OwnerContext
from .store import ALLOWED_DOMAINS, VerificationRunStore


def _timezone_hint(request: Request) -> str:
    value = request.query_params.get("timezone")
    if value:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            return "UTC"
        return value
    return "UTC"


def _request_error_payload(request: Request, error: BFFError) -> dict[str, Any]:
    request_id = _next_request_id(request)
    body = ErrorBody(
        code=error.code,
        message=error.message,
        requestId=request_id,
        retryable=error.retryable,
        field=error.field,
    )
    return serialize_error(body, timezone_name=_timezone_hint(request))


def _reject_query_params(request: Request, allowed: frozenset[str]) -> None:
    if any(key in FORBIDDEN_QUERY_KEYS for key in request.query_params):
        raise error_for("INVALID_QUERY")
    if any(key not in allowed for key in request.query_params):
        raise error_for("INVALID_QUERY")
    seen: set[str] = set()
    for key, value in request.query_params.multi_items():
        if key in seen:
            raise error_for("INVALID_QUERY", field=key)
        seen.add(key)
        if value == "":
            raise error_for("INVALID_QUERY", field=key)


MAX_CREATE_BODY_BYTES = 16 * 1024
NO_STORE_HEADER = (b"cache-control", b"no-store")


def _is_api_path(path: Any) -> bool:
    return isinstance(path, str) and (path == "/api" or path.startswith("/api/"))


def _is_loopback_client(scope: Mapping[str, Any]) -> bool:
    client = scope.get("client")
    if not isinstance(client, (tuple, list)) or not client:
        return False
    host = client[0]
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped_address = getattr(address, "ipv4_mapped", None)
    return bool(
        mapped_address.is_loopback
        if mapped_address is not None
        else address.is_loopback
    )


def _has_allowed_origin(
    scope: Mapping[str, Any], allowed_origins: frozenset[str]
) -> bool:
    origins = _header_values(scope, "origin")
    return not origins or len(origins) == 1 and origins[0] in allowed_origins


def _next_request_id(request: Request) -> str:
    try:
        app = getattr(request, "app", None)
        state = getattr(app, "state", None)
        counter = getattr(state, "request_counter", None)
        value = next(counter)
        if type(value) is not int or value < 0:
            raise ValueError("request counter returned an invalid value")
        return f"req-demo-{value:08d}"
    except Exception:
        return "req-demo-fallback"


class NoStoreMiddleware:
    """Prevent browser caches from retaining any BFF response."""

    def __init__(
        self,
        app: Any,
        *,
        dev_access_enabled: bool = False,
        allowed_origins: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.dev_access_enabled = dev_access_enabled
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        is_api_path = _is_api_path(scope.get("path", ""))
        response_started = False

        async def send_without_cache(message: dict[str, Any]) -> None:
            nonlocal response_started
            if is_api_path and message.get("type") == "http.response.start":
                response_started = True
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                headers.append(NO_STORE_HEADER)
                message = {**message, "headers": headers}
            await send(message)

        if self.dev_access_enabled and (
            not _is_loopback_client(scope)
            or not _has_allowed_origin(scope, self.allowed_origins)
        ):
            error = error_for("FORBIDDEN")
            request = Request(scope, receive)
            response = JSONResponse(
                status_code=error.status_code,
                content=_request_error_payload(request, error),
            )
            await response(scope, receive, send_without_cache)
            return

        if not is_api_path:
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send_without_cache)
        except Exception:
            if response_started:
                raise
            error = error_for("INTERNAL_ERROR")
            request = Request(scope, receive)
            response = JSONResponse(
                status_code=error.status_code,
                content=_request_error_payload(request, error),
            )
            await response(scope, receive, send_without_cache)


class BoundedBodyMiddleware:
    """Bound request chunks before FastAPI's request body cache can grow."""

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int,
        catch_errors: bool = False,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.catch_errors = catch_errors

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not _is_api_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        try:
            _reject_ambiguous_framing_headers(scope)
            declared_length = _parse_content_length(scope)
        except BFFError as exc:
            if not self.catch_errors:
                raise
            await self._send_error(scope, receive, send, exc)
            return

        is_create_route = (
            scope.get("method") == "POST"
            and scope.get("path") == "/api/v1/me/verify/runs"
        )
        if not is_create_route:
            await self.app(scope, receive, send)
            return

        if declared_length is not None:
            if declared_length > self.max_bytes:
                await self._send_error(
                    scope,
                    receive,
                    send,
                    error_for("INVALID_QUERY", field="body"),
                )
                return

        total = 0

        async def bounded_receive() -> dict[str, Any]:
            nonlocal total
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_bytes:
                    raise error_for("INVALID_QUERY", field="body")
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except BFFError as exc:
            if not self.catch_errors:
                raise
            await self._send_error(scope, bounded_receive, send, exc)

    async def _send_error(
        self, scope: dict[str, Any], receive: Any, send: Any, error: BFFError
    ) -> None:
        request = Request(scope, receive)
        request_id = _next_request_id(request)
        body = serialize_error(
            ErrorBody(
                code=error.code,
                message=error.message,
                requestId=request_id,
                retryable=error.retryable,
                field=error.field,
            ),
            timezone_name=_timezone_hint(request),
        )
        encoded = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(encoded)).encode()),
        ]
        if error.retry_after is not None:
            headers.append((b"retry-after", str(error.retry_after).encode()))
        await send(
            {
                "type": "http.response.start",
                "status": error.status_code,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": encoded})


def _header_values(scope: Mapping[str, Any], name: str) -> list[str]:
    wanted = name.lower().encode()
    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == wanted
    ]


def _reject_ambiguous_framing_headers(scope: Mapping[str, Any]) -> None:
    for name, field in (
        ("content-length", "Content-Length"),
        ("content-type", "Content-Type"),
    ):
        values = _header_values(scope, name)
        if len(values) > 1 or any("," in value for value in values):
            raise error_for("INVALID_QUERY", field=field)


def _parse_content_length(scope: Mapping[str, Any]) -> int | None:
    values = _header_values(scope, "content-length")
    if not values:
        return None
    value = values[0]
    if not value or any(character < "0" or character > "9" for character in value):
        raise error_for("INVALID_QUERY", field="Content-Length")
    try:
        return int(value)
    except ValueError as exc:
        raise error_for("INVALID_QUERY", field="Content-Length") from exc


def _reject_duplicate_headers(request: Request, names: tuple[str, ...]) -> None:
    for name in names:
        if len(_header_values(request.scope, name)) > 1:
            raise error_for("INVALID_QUERY", field=name)


def _require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type")
    if content_type is None or content_type.split(";", 1)[0].strip().lower() != (
        "application/json"
    ):
        raise error_for("INVALID_QUERY", field="Content-Type")


async def _read_json_body(request: Request) -> Mapping[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_CREATE_BODY_BYTES:
                raise error_for("INVALID_QUERY", field="body")
        except ValueError as exc:
            raise error_for("INVALID_QUERY", field="Content-Length") from exc
    body = await request.body()
    if len(body) > MAX_CREATE_BODY_BYTES:
        raise error_for("INVALID_QUERY", field="body")
    try:
        value = json.loads(body, object_pairs_hook=_reject_duplicate_json_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise error_for("INVALID_QUERY", field="body") from exc
    if not isinstance(value, dict):
        raise error_for("INVALID_SCOPE")
    return value


_CREATE_BODY_FIELDS = frozenset({"date", "timezone", "domains"})


def _reject_duplicate_json_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _parse_create_body(value: Mapping[str, Any]) -> CreateRunBody:
    if any(key not in _CREATE_BODY_FIELDS for key in value):
        raise error_for("INVALID_SCOPE", field="domains")

    date_value = value.get("date")
    if "date" not in value or not isinstance(date_value, str):
        raise error_for("INVALID_QUERY", field="date")
    validate_date(date_value, field="date")

    timezone_value = value.get("timezone")
    if "timezone" not in value or not isinstance(timezone_value, str):
        raise error_for("INVALID_QUERY", field="timezone")
    if len(timezone_value) > 64:
        raise error_for("INVALID_QUERY", field="timezone")
    validate_timezone(timezone_value, field="timezone")

    domains = value.get("domains")
    if (
        not isinstance(domains, list)
        or not domains
        or len(domains) > 6
        or any(
            not isinstance(domain, str) or domain not in ALLOWED_DOMAINS
            for domain in domains
        )
    ):
        raise error_for("INVALID_SCOPE", field="domains")

    if len(set(domains)) != len(domains):
        raise error_for("INVALID_SCOPE", field="domains")

    try:
        return CreateRunBody.model_validate(value)
    except ValidationError as exc:
        fields = {str(error["loc"][0]) for error in exc.errors() if error["loc"]}
        if "date" in fields:
            raise error_for("INVALID_QUERY", field="date") from exc
        if "timezone" in fields:
            raise error_for("INVALID_QUERY", field="timezone") from exc
        raise error_for("INVALID_SCOPE", field="domains") from exc


FORBIDDEN_QUERY_KEYS = frozenset(
    {
        "adapterMappings",
        "adapter_mappings",
        "batchId",
        "batch_id",
        "credentials",
        "error",
        "metadata",
        "message",
        "owRunId",
        "ow_run_id",
        "userId",
        "user_id",
        "owUserId",
        "ow_user_id",
        "apiKey",
        "api_key",
        "url",
        "path",
        "payload",
        "runId",
        "run_id",
        "token",
    }
)


def create_app(
    *,
    adapter: Any | None = None,
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
    ow_api_base_url: str | None = None,
    ow_bearer_token: str | None = None,
    ow_api_key: str | None = None,
    ow_timeout_seconds: float | str | None = None,
    live_transport: Any | None = None,
    store: VerificationRunStore | None = None,
) -> FastAPI:
    settings = Settings.from_environment(
        environment=environment,
        session_mode=session_mode,
        dev_access_enabled=dev_access_enabled,
        session_key=session_key,
        principal_key=principal_key,
        owner_key=owner_key,
        ow_user_key=ow_user_key,
        allowed_origin=allowed_origin,
        cursor_ttl_seconds=cursor_ttl_seconds,
        fixture_case=fixture_case,
        live_ow_enabled=live_ow_enabled,
        ow_api_base_url=ow_api_base_url,
        ow_bearer_token=ow_bearer_token,
        ow_api_key=ow_api_key,
        ow_timeout_seconds=ow_timeout_seconds,
    )
    if adapter is not None:
        selected_adapter = adapter
    elif settings.live_ow_enabled:
        expected_owner_context = OwnerContext(
            principal_key=settings.principal_key,
            owner_key=settings.owner_key,
            ow_user_key=settings.ow_user_key,
        )
        if (
            settings.ow_api_base_url is None
            or settings.ow_bearer_token is None
            and settings.ow_api_key is None
        ):
            raise ValueError("live OW configuration is incomplete")
        selected_adapter = LiveOWAdapter(
            base_url=settings.ow_api_base_url,
            bearer_token=settings.ow_bearer_token,
            api_key=settings.ow_api_key,
            expected_owner_context=expected_owner_context,
            timeout_seconds=settings.ow_timeout_seconds,
            transport=live_transport,
        )
    else:
        selected_adapter = load_offline_fixture_adapter()
    selected_store = store or VerificationRunStore(
        cursor_ttl_seconds=settings.cursor_ttl_seconds
    )
    service = BFFService(
        adapter=selected_adapter,
        settings=settings,
        store=selected_store,
    )

    app = FastAPI(
        title="Enano Coach BFF",
        version="bff-ui-v1",
        redirect_slashes=False,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service
    app.state.request_counter = count(1)
    app.add_middleware(
        BoundedBodyMiddleware,
        max_bytes=MAX_CREATE_BODY_BYTES,
        catch_errors=True,
    )
    app.add_middleware(
        NoStoreMiddleware,
        dev_access_enabled=settings.dev_access_enabled,
        allowed_origins=settings.allowed_origins,
    )

    @app.exception_handler(BFFError)
    async def bff_error_handler(request: Request, exc: BFFError) -> JSONResponse:
        headers: dict[str, str] = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content=_request_error_payload(request, exc),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        error = error_for("INVALID_QUERY")
        return JSONResponse(
            status_code=error.status_code,
            content=_request_error_payload(request, error),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            error = error_for("NOT_FOUND")
        elif exc.status_code == 405:
            error = error_for("METHOD_NOT_ALLOWED")
        else:
            error = error_for("INVALID_QUERY")
        return JSONResponse(
            status_code=error.status_code,
            content=_request_error_payload(request, error),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request, _exc: Exception
    ) -> JSONResponse:
        error = error_for("INTERNAL_ERROR")
        return JSONResponse(
            status_code=error.status_code,
            content=_request_error_payload(request, error),
        )

    @app.get("/api/v1/session")
    async def get_session(request: Request) -> JSONResponse:
        _reject_query_params(request, frozenset())
        return JSONResponse(content=service.session_payload())

    @app.get("/api/v1/me/verify/overview")
    async def get_overview(
        request: Request,
        date: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ) -> JSONResponse:
        service.require_active()
        _reject_query_params(request, frozenset({"date", "timezone"}))
        logical_date, parsed_date, timezone_name = service.validate_context(
            date, timezone
        )
        return JSONResponse(
            content=service.overview(
                logical_date=logical_date,
                parsed_date=parsed_date,
                timezone_name=timezone_name,
            )
        )

    @app.get("/api/v1/me/verify/sources")
    async def get_sources(
        request: Request,
        date: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ) -> JSONResponse:
        service.require_active()
        _reject_query_params(request, frozenset({"date", "timezone"}))
        logical_date, _parsed_date, timezone_name = service.optional_context(
            date, timezone
        )
        return JSONResponse(
            content=service.sources(
                logical_date=logical_date, timezone_name=timezone_name
            )
        )

    @app.get("/api/v1/me/verify/activity-trend")
    async def get_activity_trend(
        request: Request,
        date: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
        range: str | None = Query(default=None),
    ) -> JSONResponse:
        service.require_active()
        _reject_query_params(request, frozenset({"date", "timezone", "range"}))
        logical_date, parsed_date, timezone_name = service.validate_context(
            date, timezone
        )
        return JSONResponse(
            content=service.activity_trend(
                logical_date=logical_date,
                parsed_date=parsed_date,
                timezone_name=timezone_name,
                range_name="7d" if range is None else range,
            )
        )

    @app.get("/api/v1/me/verify/settings")
    async def get_settings(request: Request) -> JSONResponse:
        service.require_active()
        _reject_query_params(request, frozenset())
        return JSONResponse(content=service.settings_payload())

    @app.get("/api/v1/me/verify/runs")
    async def get_runs(
        request: Request,
        from_value: str | None = Query(default=None, alias="from"),
        to_value: str | None = Query(default=None, alias="to"),
        state: str | None = Query(default=None),
        limit: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        timezone: str | None = Query(default=None),
    ) -> JSONResponse:
        service.require_active()
        _reject_query_params(
            request,
            frozenset({"from", "to", "state", "limit", "cursor", "timezone"}),
        )
        return JSONResponse(
            content=service.list_runs(
                from_value=from_value,
                to_value=to_value,
                state=state,
                limit_value=limit,
                cursor=cursor,
                timezone_value=timezone,
            )
        )

    @app.post("/api/v1/me/verify/runs")
    async def post_run(request: Request) -> JSONResponse:
        _reject_duplicate_headers(request, ("Origin", "Idempotency-Key"))
        service.require_active()
        _reject_query_params(request, frozenset())
        _require_json_content_type(request)
        body_data = await _read_json_body(request)
        body = _parse_create_body(body_data)
        payload, record = service.create_run(
            body=body,
            idempotency_key=request.headers.get("idempotency-key"),
            origin=request.headers.get("origin"),
        )
        return JSONResponse(
            status_code=202,
            content=payload,
            headers={"Location": f"/api/v1/me/verify/runs/{record.run_key}"},
        )

    @app.get("/api/v1/me/verify/runs/{run_key}")
    async def get_run(request: Request, run_key: str) -> JSONResponse:
        service.require_active()
        _reject_query_params(request, frozenset())
        return JSONResponse(content=service.run_detail(run_key))

    return app


def _create_default_app() -> FastAPI:
    if not os.getenv("BFF_ENVIRONMENT"):
        # Importing the module must never activate synthetic protected access
        # without an explicit server environment.
        return create_app(environment="test", session_mode="anonymous")
    return create_app()


app = _create_default_app()
