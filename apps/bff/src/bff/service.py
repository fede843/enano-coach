from __future__ import annotations

import re
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapter.offline import FixtureContractError, OfflineFixtureAdapter

from .config import Settings
from .errors import ErrorCode, error_for
from .models import CreateRunBody
from .serializers import (
    serialize_overview,
    serialize_run_create,
    serialize_run_detail,
    serialize_run_list,
    serialize_session,
    serialize_settings,
    serialize_sources,
    serialize_stored_run_create,
    validate_adapter_error_response,
    validate_adapter_run_detail_response,
    validate_adapter_run_list_response,
)
from .session import (
    OwnerContext,
    SessionContext,
    require_active_session,
    session_from_settings,
)
from .store import (
    ALLOWED_DOMAINS,
    RUN_STATES,
    CursorContext,
    RunRecord,
    VerificationRunStore,
)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_IDEMPOTENCY_PARTS = frozenset(
    {
        "apikey",
        "batchid",
        "credential",
        "manifestid",
        "owrunid",
        "owuserid",
        "password",
        "path",
        "payload",
        "runid",
        "secret",
        "token",
        "url",
        "userid",
        "useruid",
    }
)
FIXTURE_ERROR_CASES = frozenset(
    {
        "overview_error",
        "upstream_invalid_502",
        "upstream_unavailable_503",
        "upstream_timeout_504",
        "rate_limited_429",
        "internal_error_500",
    }
)
FIXTURE_ERROR_CODES: dict[str, tuple[ErrorCode, int | None]] = {
    "overview_error": ("UPSTREAM_TIMEOUT", 5),
    "upstream_invalid_502": ("UPSTREAM_INVALID", None),
    "upstream_unavailable_503": ("UPSTREAM_UNAVAILABLE", 5),
    "upstream_timeout_504": ("UPSTREAM_TIMEOUT", 5),
    "rate_limited_429": ("RATE_LIMITED", 30),
    "internal_error_500": ("INTERNAL_ERROR", None),
}
ADAPTER_ERROR_CODES: dict[str, tuple[ErrorCode, int | None]] = {
    "UPSTREAM_INVALID": ("UPSTREAM_INVALID", None),
    "UPSTREAM_UNAVAILABLE": ("UPSTREAM_UNAVAILABLE", 5),
    "UPSTREAM_TIMEOUT": ("UPSTREAM_TIMEOUT", 5),
    "RATE_LIMITED": ("RATE_LIMITED", 30),
    "INTERNAL_ERROR": ("INTERNAL_ERROR", None),
}


class _OfflineAdapterBoundary:
    """Bind the legacy fixture adapter to the server-only adapter interface."""

    def __init__(self, adapter: OfflineFixtureAdapter) -> None:
        self.adapter = adapter

    def get_bff_response(
        self, case: str, *, owner_context: OwnerContext
    ) -> dict[str, Any]:
        del owner_context
        return self.adapter.get_bff_response(case)


class _OwnerBoundAdapter:
    def __init__(self, adapter: Any, owner_context: OwnerContext) -> None:
        self.adapter = adapter
        self.owner_context = owner_context

    def get_bff_response(self, case: str) -> Any:
        return self.adapter.get_bff_response(
            case,
            owner_context=self.owner_context,
        )


def bind_adapter(adapter: Any) -> Any:
    if isinstance(adapter, OfflineFixtureAdapter):
        return _OfflineAdapterBoundary(adapter)
    return adapter


def validate_date(value: str | None, *, field: str = "date") -> tuple[str, date_type]:
    if value is None or not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise error_for("INVALID_QUERY", field=field)
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError as exc:
        raise error_for("INVALID_QUERY", field=field) from exc
    return value, parsed


def validate_timezone(value: str | None, *, field: str = "timezone") -> str:
    if value is None or not isinstance(value, str) or not value:
        raise error_for("INVALID_QUERY", field=field)
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise error_for("INVALID_QUERY", field=field) from exc
    return value


def local_midnight_window(
    logical_date: date_type, timezone_name: str
) -> tuple[str, str]:
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(logical_date, time.min, tzinfo=zone)
    end = datetime.combine(logical_date + timedelta(days=1), time.min, tzinfo=zone)
    values = tuple(
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
        for value in (start, end)
    )
    return values[0], values[1]


def normalize_run_state(
    stage: str,
    status: str | None,
    *,
    closed_mismatch: bool = False,
    not_verifiable: bool = False,
) -> str:
    if stage in {
        "queued",
        "started",
        "fetching",
        "processing",
        "saving",
    } and status in {
        None,
        "in_progress",
        "accepted",
    }:
        return "pending"
    if status == "failed" or stage == "failed":
        return "failed"
    if status == "cancelled" or stage == "cancelled":
        return "cancelled"
    if stage == "completed" and status == "partial":
        return "partial"
    if stage == "completed" and status == "skipped":
        return "skipped"
    if stage == "completed" and status == "in_progress":
        return "inconclusive"
    if stage == "completed" and status == "success":
        if closed_mismatch:
            return "completed_with_findings"
        if not_verifiable:
            return "not_verifiable"
        return "persisted"
    return "inconclusive"


def validate_idempotency_key(value: str | None) -> str:
    if (
        value is None
        or not isinstance(value, str)
        or not IDEMPOTENCY_PATTERN.fullmatch(value)
    ):
        raise error_for("INVALID_QUERY", field="Idempotency-Key")
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if any(part in normalized for part in _FORBIDDEN_IDEMPOTENCY_PARTS):
        raise error_for("INVALID_QUERY", field="Idempotency-Key")
    return value


class BFFService:
    def __init__(
        self,
        *,
        adapter: Any,
        settings: Settings,
        store: VerificationRunStore,
    ) -> None:
        self.adapter = bind_adapter(adapter)
        self.settings = settings
        self.store = store
        self.session = session_from_settings(settings)

    def session_payload(self) -> dict[str, Any]:
        if self.session.mode == "active":
            response = self._adapter_response("session_active")
            self._raise_for_adapter_error(response)
            return serialize_session(
                response,
                authenticated=True,
                access_state="active",
                can_read_verification=True,
            )
        if self.session.mode == "anonymous":
            return serialize_session(
                {},
                authenticated=False,
                access_state="anonymous",
                can_read_verification=False,
            )
        return serialize_session(
            {},
            authenticated=self.session.authenticated,
            access_state=self.session.access_state,
            can_read_verification=self.session.can_read_verification,
        )

    def require_active(self) -> SessionContext:
        session = require_active_session(self.session)
        if session.owner_context is None:
            raise error_for("FORBIDDEN")
        return session

    def _owner_context(self) -> OwnerContext:
        owner_context = self.session.owner_context
        if owner_context is None:
            raise error_for("FORBIDDEN")
        return owner_context

    def validate_context(
        self, date_value: str | None, timezone_value: str | None
    ) -> tuple[str, date_type, str]:
        logical_date, parsed_date = validate_date(date_value)
        timezone_name = validate_timezone(timezone_value)
        return logical_date, parsed_date, timezone_name

    def optional_context(
        self, date_value: str | None, timezone_value: str | None
    ) -> tuple[str, date_type, str]:
        if date_value is None:
            date_value = "2024-01-02"
        if timezone_value is None:
            timezone_value = "UTC"
        return self.validate_context(date_value, timezone_value)

    def _check_dependency_case(self) -> None:
        case = self.settings.fixture_case
        if case not in FIXTURE_ERROR_CASES:
            return
        response = self._adapter_response(case)
        validate_adapter_error_response(response)
        code, retry_after = FIXTURE_ERROR_CODES[case]
        raise error_for(code, retry_after=retry_after)

    def overview(
        self, *, logical_date: str, parsed_date: date_type, timezone_name: str
    ) -> dict[str, Any]:
        self._owner_context()
        self._check_dependency_case()
        start, end = local_midnight_window(parsed_date, timezone_name)
        case = ""
        live_getter = getattr(self.adapter, "get_overview_response", None)
        if live_getter is None:
            case = (
                "overview_mixed" if logical_date == "2024-01-02" else "overview_empty"
            )
            response = self._adapter_response(case)
        else:
            response = live_getter(
                logical_date=logical_date,
                timezone_name=timezone_name,
                from_utc=start,
                to_utc=end,
                owner_context=self._owner_context(),
            )
        self._raise_for_adapter_error(response)
        return serialize_overview(
            response,
            logical_date=logical_date,
            timezone_name=timezone_name,
            from_utc=start,
            to_utc=end,
            allow_empty_date_projection=case == "overview_empty",
        )

    def sources(self, *, logical_date: str, timezone_name: str) -> dict[str, Any]:
        self._owner_context()
        self._check_dependency_case()
        live_getter = getattr(self.adapter, "get_sources_response", None)
        if live_getter is None:
            case = (
                "source_ready" if logical_date == "2024-01-02" else "source_ambiguous"
            )
            response = self._adapter_response(case)
        else:
            response = live_getter(
                logical_date=logical_date,
                timezone_name=timezone_name,
                owner_context=self._owner_context(),
            )
        self._raise_for_adapter_error(response)
        return serialize_sources(response, timezone_name=timezone_name)

    def settings_payload(self) -> dict[str, Any]:
        self._owner_context()
        self._check_dependency_case()
        response = self._adapter_response("settings_capabilities")
        self._raise_for_adapter_error(response)
        return serialize_settings(response)

    def list_runs(
        self,
        *,
        from_value: str | None,
        to_value: str | None,
        state: str | None,
        limit_value: str | None,
        cursor: str | None,
        timezone_value: str | None,
    ) -> dict[str, Any]:
        owner_context = self._owner_context()
        timezone_name = validate_timezone(
            "UTC" if timezone_value is None else timezone_value
        )
        from_date = None
        to_date = None
        if from_value is not None:
            _, from_date = validate_date(from_value, field="from")
        if to_value is not None:
            _, to_date = validate_date(to_value, field="to")
        if from_date is not None and to_date is not None and from_date > to_date:
            raise error_for("INVALID_QUERY", field="from")
        if state is not None and state not in RUN_STATES:
            raise error_for("INVALID_QUERY", field="state")
        limit = 25
        if limit_value is not None:
            try:
                limit = int(limit_value)
            except (TypeError, ValueError) as exc:
                raise error_for("INVALID_QUERY", field="limit") from exc
        if not 1 <= limit <= 100:
            raise error_for("INVALID_QUERY", field="limit")

        context = CursorContext(
            session_key=self.session.session_key,
            from_date=from_value,
            to_date=to_value,
            state=state,
            limit=limit,
            timezone=timezone_name,
            owner_key=owner_context.owner_key,
            ow_user_key=owner_context.ow_user_key,
        )
        self.store.validate_cursor(cursor=cursor, context=context)
        self._ensure_store_seeded()
        self._check_dependency_case()
        records, next_cursor, has_next = self.store.list_page(
            context=context,
            from_date=from_date,
            to_date=to_date,
            state=state,
            cursor=cursor,
        )
        response = self._adapter_response(
            "runs_second_page"
            if cursor is not None and not has_next
            else "runs_first_page"
        )
        self._raise_for_adapter_error(response)
        validate_adapter_run_list_response(response)
        return serialize_run_list(
            response,
            records=records,
            next_cursor=next_cursor,
            has_next=has_next,
            timezone_name=timezone_name,
        )

    def create_run(
        self,
        *,
        body: CreateRunBody,
        idempotency_key: str | None,
        origin: str | None,
    ) -> tuple[dict[str, Any], RunRecord]:
        owner_context = self._owner_context()
        if origin not in self.settings.allowed_origins:
            raise error_for("FORBIDDEN")
        idempotency_key = validate_idempotency_key(idempotency_key)
        logical_date, _parsed_date = validate_date(body.date)
        timezone_name = validate_timezone(body.timezone)
        if len(set(body.domains)) != len(body.domains):
            raise error_for("INVALID_SCOPE", field="domains")
        domains = tuple(sorted(set(body.domains)))
        if not domains or any(domain not in ALLOWED_DOMAINS for domain in domains):
            raise error_for("INVALID_SCOPE", field="domains")

        existing = self.store.lookup_idempotency(
            owner_session_key=self.session.session_key,
            scope_date=logical_date,
            scope_timezone=timezone_name,
            domains=domains,
            idempotency_key=idempotency_key,
            owner_key=owner_context.owner_key,
            ow_user_key=owner_context.ow_user_key,
        )
        if existing is not None:
            return (
                serialize_stored_run_create(
                    record=existing,
                    timezone_name=timezone_name,
                ),
                existing,
            )

        self._ensure_store_seeded()
        self._check_dependency_case()
        response = self._adapter_response("verification_run_create")
        self._raise_for_adapter_error(response)
        validate_adapter_run_detail_response(response)
        record, created = self.store.prepare_create(
            owner_session_key=self.session.session_key,
            scope_date=logical_date,
            scope_timezone=timezone_name,
            domains=domains,
            idempotency_key=idempotency_key,
            owner_key=owner_context.owner_key,
            ow_user_key=owner_context.ow_user_key,
        )
        try:
            payload = serialize_run_create(
                response, record=record, timezone_name=timezone_name
            )
        except Exception:
            if created:
                self.store.rollback_create(
                    owner_session_key=self.session.session_key,
                    idempotency_key=idempotency_key,
                    record=record,
                    scope_date=logical_date,
                    scope_timezone=timezone_name,
                    domains=domains,
                    owner_key=owner_context.owner_key,
                    ow_user_key=owner_context.ow_user_key,
                )
            raise
        if created:
            self.store.commit_create(
                owner_session_key=self.session.session_key,
                idempotency_key=idempotency_key,
                record=record,
                scope_date=logical_date,
                scope_timezone=timezone_name,
                domains=domains,
                owner_key=owner_context.owner_key,
                ow_user_key=owner_context.ow_user_key,
            )
        return payload, record

    def run_detail(self, run_key: str) -> dict[str, Any]:
        owner_context = self._owner_context()
        if not re.fullmatch(r"verify-demo-[a-z0-9-]+", run_key):
            raise error_for("RUN_NOT_FOUND")
        record = self.store.get(
            run_key,
            self.session.session_key,
            owner_key=owner_context.owner_key,
            ow_user_key=owner_context.ow_user_key,
        )
        if record is None:
            if self.store.has_foreign_run(
                run_key,
                self.session.session_key,
                owner_context.owner_key,
                owner_context.ow_user_key,
            ):
                raise error_for("RUN_NOT_FOUND")
            self._ensure_store_seeded()
            record = self.store.get(
                run_key,
                self.session.session_key,
                owner_key=owner_context.owner_key,
                ow_user_key=owner_context.ow_user_key,
            )
        if record is None:
            raise error_for("RUN_NOT_FOUND")
        self._check_dependency_case()
        response = self._adapter_response(
            {
                "partial": "verification_run_partial",
                "not_verifiable": "verification_not_verifiable",
                "completed_with_findings": "verification_run_mismatch",
                "inconclusive": "verification_inconclusive",
            }.get(record.state, "verification_run_create")
        )
        self._raise_for_adapter_error(response)
        validate_adapter_run_detail_response(response)
        return serialize_run_detail(
            response, record=record, timezone_name=record.scope_timezone
        )

    @staticmethod
    def _raise_for_adapter_error(response: Any) -> None:
        if not isinstance(response, dict):
            raise error_for("UPSTREAM_INVALID")
        error = response.get("error")
        if error is None:
            return
        validate_adapter_error_response(response)
        code = error.get("code")
        if code in ADAPTER_ERROR_CODES:
            mapped_code, retry_after = ADAPTER_ERROR_CODES[code]
            raise error_for(mapped_code, retry_after=retry_after)
        raise error_for("UPSTREAM_INVALID")

    def _ensure_store_seeded(self) -> None:
        owner_context = self._owner_context()
        seed_context = (
            self.session.session_key,
            owner_context.owner_key,
            owner_context.ow_user_key,
        )
        if self.store.is_seeded(*seed_context):
            return
        self.store.seed_from_adapter(
            _OwnerBoundAdapter(self.adapter, owner_context),
            self.session.session_key,
            owner_key=owner_context.owner_key,
            ow_user_key=owner_context.ow_user_key,
        )

    def _adapter_response(self, case: str) -> Any:
        try:
            return self.adapter.get_bff_response(
                case,
                owner_context=self._owner_context(),
            )
        except FixtureContractError as exc:
            raise error_for("UPSTREAM_INVALID") from exc
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise error_for("UPSTREAM_INVALID") from exc
