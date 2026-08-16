from __future__ import annotations

import re
import secrets
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .errors import BFFError, error_for

_CURSOR_TOKEN_PATTERN = re.compile(r"^c_[A-Za-z0-9_-]{8,64}$")

ALLOWED_DOMAINS = frozenset(
    {"activity", "sleep", "recovery", "body", "workouts", "sources"}
)
RUN_STATES = frozenset(
    {
        "pending",
        "persisted",
        "partial",
        "failed",
        "cancelled",
        "skipped",
        "completed_with_findings",
        "not_verifiable",
        "inconclusive",
    }
)


def _normalize_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(domains)))


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _counts(value: dict[str, Any] | None) -> dict[str, int | None]:
    source = value or {}
    return {
        "recordsSeen": source.get("recordsSeen"),
        "recordsAccepted": source.get("recordsAccepted"),
        "recordsRejected": source.get("recordsRejected"),
        "recordsDuplicated": source.get("recordsDuplicated"),
        "fieldsUnsupported": source.get("fieldsUnsupported"),
    }


@dataclass
class RunRecord:
    run_key: str
    owner_session_key: str
    state: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    scope_date: str
    scope_timezone: str
    domains: tuple[str, ...]
    counts: dict[str, int | None]
    warnings: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] | None = None
    listed: bool = True

    def scope(self) -> dict[str, Any]:
        return {
            "date": self.scope_date,
            "timezone": self.scope_timezone,
            "domains": list(self.domains),
        }

    def idempotency_scope(self) -> tuple[str, str, tuple[str, ...]]:
        return self.scope_date, self.scope_timezone, _normalize_domains(self.domains)


@dataclass(frozen=True)
class CursorContext:
    session_key: str
    from_date: str | None
    to_date: str | None
    state: str | None
    limit: int
    timezone: str
    schema_version: str = "1"
    ordering: str = "requestedAt.desc,runKey.asc"


@dataclass
class CursorRecord:
    context: CursorContext
    position: int
    expires_at: datetime
    run_keys: tuple[str, ...]


class VerificationRunStore:
    """In-memory control-plane aggregates; it never stores health facts or raw data."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 300,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._runs: dict[str, RunRecord] = {}
        self._idempotency: dict[
            tuple[str, str], tuple[tuple[str, str, tuple[str, ...]], str]
        ] = {}
        self._cursors: dict[str, CursorRecord] = {}
        self._next_number = 1

    def _snapshot_state(self) -> tuple[Any, Any, Any, int]:
        return (
            deepcopy(self._runs),
            deepcopy(self._idempotency),
            deepcopy(self._cursors),
            self._next_number,
        )

    def _restore_state(self, snapshot: tuple[Any, Any, Any, int]) -> None:
        runs, idempotency, cursors, next_number = snapshot
        self._runs.clear()
        self._runs.update(deepcopy(runs))
        self._idempotency.clear()
        self._idempotency.update(deepcopy(idempotency))
        self._cursors.clear()
        self._cursors.update(deepcopy(cursors))
        self._next_number = next_number

    def seed_from_adapter(self, adapter: Any, owner_session_key: str) -> None:
        snapshot = self._snapshot_state()
        try:
            first_page = adapter.get_bff_response("runs_first_page")
            second_page = adapter.get_bff_response("runs_second_page")
            from .serializers import (
                project_seed_run_item,
                project_seed_verification_run,
                validate_adapter_run_detail_response,
                validate_adapter_run_list_response,
            )

            validate_adapter_run_list_response(first_page)
            validate_adapter_run_list_response(second_page)

            staged_items: list[tuple[dict[str, Any], bool]] = []
            for item in first_page["data"]["items"] + second_page["data"]["items"]:
                staged_items.append((project_seed_run_item(item), True))

            detail_cases = (
                "verification_run_create",
                "verification_run_partial",
                "verification_not_verifiable",
                "verification_run_mismatch",
                "verification_inconclusive",
            )
            for case in detail_cases:
                response = adapter.get_bff_response(case)
                validate_adapter_run_detail_response(response)
                item = response["data"]["verificationRun"]
                staged_items.append((project_seed_verification_run(item), False))

            # Do not expose a partially-seeded store if a later candidate fails
            # boundary validation. All adapter records are checked first.
            for item, listed in staged_items:
                self._install_item(item, owner_session_key, listed=listed)
        except BFFError:
            self._restore_state(snapshot)
            raise
        except Exception as exc:
            self._restore_state(snapshot)
            raise error_for("UPSTREAM_INVALID") from exc

    def _install_item(
        self, item: dict[str, Any], owner_session_key: str, *, listed: bool
    ) -> None:
        run_key = item["runKey"]
        existing = self._runs.get(run_key)
        if existing is not None and not listed:
            existing.state = item["state"]
            existing.requested_at = (
                _timestamp(item["requestedAt"]) or existing.requested_at
            )
            existing.started_at = _timestamp(item.get("startedAt"))
            existing.finished_at = _timestamp(item.get("finishedAt"))
            scope = item.get("scope", {})
            existing.scope_date = scope.get("date", existing.scope_date)
            existing.scope_timezone = scope.get("timezone", existing.scope_timezone)
            existing.domains = tuple(scope.get("domains", existing.domains))
            existing.counts = _counts(item.get("counts"))
            existing.warnings = item.get("warnings", [])
            existing.results = item.get("results")
            return
        if existing is not None:
            return
        requested_at = _timestamp(item["requestedAt"])
        if requested_at is None:
            raise ValueError("synthetic run requires requestedAt")
        scope = item.get("scope", {})
        domains = tuple(scope.get("domains", ("activity",)))
        record = RunRecord(
            run_key=run_key,
            owner_session_key=owner_session_key,
            state=item["state"],
            requested_at=requested_at,
            started_at=_timestamp(item.get("startedAt")),
            finished_at=_timestamp(item.get("finishedAt")),
            scope_date=scope.get("date", "2024-01-02"),
            scope_timezone=scope.get("timezone", "UTC"),
            domains=domains,
            counts=_counts(item.get("counts")),
            warnings=item.get("warnings", []),
            results=item.get("results"),
            listed=listed,
        )
        self._runs[record.run_key] = record
        self._next_number = max(self._next_number, self._key_number(record.run_key) + 1)

    @staticmethod
    def _key_number(run_key: str) -> int:
        try:
            return int(run_key.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            return 0

    def get(self, run_key: str, owner_session_key: str) -> RunRecord | None:
        record = self._runs.get(run_key)
        if record is None or record.owner_session_key != owner_session_key:
            return None
        return record

    @property
    def is_empty(self) -> bool:
        return not self._runs

    def _next_run_key(self) -> str:
        number = self._next_number
        while f"verify-demo-{number:02d}" in self._runs:
            number += 1
        return f"verify-demo-{number:02d}"

    def prepare_create(
        self,
        *,
        owner_session_key: str,
        scope_date: str,
        scope_timezone: str,
        domains: tuple[str, ...],
        idempotency_key: str,
    ) -> tuple[RunRecord, bool]:
        normalized_domains = _normalize_domains(domains)
        scope = (scope_date, scope_timezone, normalized_domains)
        idempotency_index = (owner_session_key, idempotency_key)
        previous = self._idempotency.get(idempotency_index)
        if previous is not None:
            previous_scope, previous_key = previous
            if previous_scope != scope:
                raise error_for("IDEMPOTENCY_CONFLICT")
            record = self._runs.get(previous_key)
            if record is None:
                raise error_for("UPSTREAM_INVALID")
            return record, False

        now = self._now()
        record = RunRecord(
            run_key=self._next_run_key(),
            owner_session_key=owner_session_key,
            state="pending",
            requested_at=now,
            started_at=None,
            finished_at=None,
            scope_date=scope_date,
            scope_timezone=scope_timezone,
            domains=normalized_domains,
            counts=_counts(None),
            listed=True,
        )
        return record, True

    def commit_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: RunRecord,
    ) -> None:
        idempotency_index = (owner_session_key, idempotency_key)
        if idempotency_index in self._idempotency:
            raise error_for("IDEMPOTENCY_CONFLICT")
        if record.run_key in self._runs:
            raise error_for("IDEMPOTENCY_CONFLICT")
        snapshot = self._snapshot_state()
        try:
            self._runs[record.run_key] = record
            self._next_number = max(
                self._next_number, self._key_number(record.run_key) + 1
            )
            self._idempotency[idempotency_index] = (
                record.idempotency_scope(),
                record.run_key,
            )
            self._finalize_create(
                owner_session_key=owner_session_key,
                idempotency_key=idempotency_key,
                record=record,
            )
        except Exception:
            self._restore_state(snapshot)
            raise

    def _finalize_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: RunRecord,
    ) -> None:
        """Keep post-insertion work inside the commit transaction."""

        del owner_session_key, idempotency_key, record

    def create(
        self,
        *,
        owner_session_key: str,
        scope_date: str,
        scope_timezone: str,
        domains: tuple[str, ...],
        idempotency_key: str,
    ) -> tuple[RunRecord, bool]:
        record, created = self.prepare_create(
            owner_session_key=owner_session_key,
            scope_date=scope_date,
            scope_timezone=scope_timezone,
            domains=domains,
            idempotency_key=idempotency_key,
        )
        if created:
            self.commit_create(
                owner_session_key=owner_session_key,
                idempotency_key=idempotency_key,
                record=record,
            )
        return record, created

    def lookup_idempotency(
        self,
        *,
        owner_session_key: str,
        scope_date: str,
        scope_timezone: str,
        domains: tuple[str, ...],
        idempotency_key: str,
    ) -> RunRecord | None:
        """Resolve an existing key without changing control-plane state."""

        previous = self._idempotency.get((owner_session_key, idempotency_key))
        if previous is None:
            return None
        previous_scope, previous_key = previous
        if previous_scope != (
            scope_date,
            scope_timezone,
            _normalize_domains(domains),
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")
        record = self._runs.get(previous_key)
        if record is None:
            raise error_for("UPSTREAM_INVALID")
        return record

    def rollback_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: RunRecord,
    ) -> None:
        """Remove a newly-created record when boundary validation fails."""

        if self._runs.get(record.run_key) is record:
            del self._runs[record.run_key]
        idempotency_index = (owner_session_key, idempotency_key)
        mapping = self._idempotency.get(idempotency_index)
        if mapping is not None and mapping[1] == record.run_key:
            del self._idempotency[idempotency_index]

    def _filtered(
        self,
        *,
        owner_session_key: str,
        from_date: date | None,
        to_date: date | None,
        state: str | None,
        timezone_name: str,
    ) -> list[RunRecord]:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(timezone_name)
        records = [
            record
            for record in self._runs.values()
            if record.owner_session_key == owner_session_key
            and record.listed
            and (state is None or record.state == state)
        ]
        if from_date is not None:
            records = [
                record
                for record in records
                if record.requested_at.astimezone(zone).date() >= from_date
            ]
        if to_date is not None:
            records = [
                record
                for record in records
                if record.requested_at.astimezone(zone).date() <= to_date
            ]
        records.sort(
            key=lambda record: (-record.requested_at.timestamp(), record.run_key)
        )
        return records

    def validate_cursor(self, *, cursor: str | None, context: CursorContext) -> None:
        """Validate cursor-only state without reading seeded run data."""

        if cursor is None:
            return
        if not isinstance(cursor, str) or not _CURSOR_TOKEN_PATTERN.fullmatch(cursor):
            raise error_for("INVALID_CURSOR", field="cursor")
        cursor_record = self._cursors.get(cursor)
        if cursor_record is None:
            raise error_for("INVALID_CURSOR", field="cursor")
        if self._now() >= cursor_record.expires_at:
            raise error_for("CURSOR_EXPIRED", field="cursor", retry_after=5)
        if cursor_record.context != context:
            raise error_for("CURSOR_CONTEXT_MISMATCH", field="cursor")

    def list_page(
        self,
        *,
        context: CursorContext,
        from_date: date | None,
        to_date: date | None,
        state: str | None,
        cursor: str | None,
    ) -> tuple[list[RunRecord], str | None, bool]:
        records = self._filtered(
            owner_session_key=context.session_key,
            from_date=from_date,
            to_date=to_date,
            state=state,
            timezone_name=context.timezone,
        )
        position = 0
        if cursor is not None:
            self.validate_cursor(cursor=cursor, context=context)
            cursor_record = self._cursors[cursor]
            records = [self._runs[key] for key in cursor_record.run_keys]
            position = cursor_record.position

        page = records[position : position + context.limit]
        next_position = position + len(page)
        has_next = next_position < len(records)
        next_cursor = None
        if has_next:
            next_cursor = self._register_cursor(
                context,
                next_position,
                tuple(record.run_key for record in records),
            )
        return page, next_cursor, has_next

    def _register_cursor(
        self, context: CursorContext, position: int, run_keys: tuple[str, ...]
    ) -> str:
        token = "c_" + secrets.token_urlsafe(18)
        self._cursors[token] = CursorRecord(
            context=context,
            position=position,
            expires_at=self._now() + timedelta(seconds=self._cursor_ttl_seconds),
            run_keys=run_keys,
        )
        return token
