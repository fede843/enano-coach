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


CreateScope = tuple[str, str, tuple[str, ...]]
IdempotencyIndex = tuple[str, str | None, str | None, str]
PreparedRequest = tuple[str, str | None, str | None, str, CreateScope]
SeedContext = tuple[str, str | None, str | None]


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
    owner_key: str | None = None
    ow_user_key: str | None = None
    idempotency_key: str | None = None

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
    owner_key: str | None = None
    ow_user_key: str | None = None


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
        self._idempotency: dict[IdempotencyIndex, tuple[CreateScope, str]] = {}
        self._cursors: dict[str, CursorRecord] = {}
        self._prepared: dict[str, RunRecord] = {}
        self._prepared_requests: dict[str, PreparedRequest] = {}
        self._seeded_contexts: set[SeedContext] = set()
        self._next_number = 1

    def _snapshot_state(self) -> tuple[Any, Any, Any, int, Any, Any, Any]:
        return (
            deepcopy(self._runs),
            deepcopy(self._idempotency),
            deepcopy(self._cursors),
            self._next_number,
            dict(self._prepared),
            dict(self._prepared_requests),
            set(self._seeded_contexts),
        )

    def _restore_state(
        self, snapshot: tuple[Any, Any, Any, int, Any, Any, Any]
    ) -> None:
        (
            runs,
            idempotency,
            cursors,
            next_number,
            prepared,
            prepared_requests,
            seeded_contexts,
        ) = snapshot
        self._runs.clear()
        self._runs.update(deepcopy(runs))
        self._idempotency.clear()
        self._idempotency.update(deepcopy(idempotency))
        self._cursors.clear()
        self._cursors.update(deepcopy(cursors))
        self._prepared.clear()
        self._prepared.update(prepared)
        self._prepared_requests.clear()
        self._prepared_requests.update(prepared_requests)
        self._seeded_contexts.clear()
        self._seeded_contexts.update(seeded_contexts)
        self._next_number = next_number

    def seed_from_adapter(
        self,
        adapter: Any,
        owner_session_key: str,
        *,
        owner_key: str,
        ow_user_key: str | None = None,
    ) -> None:
        seed_context = (owner_session_key, owner_key, ow_user_key)
        if seed_context in self._seeded_contexts:
            return
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
            run_key_map: dict[str, str] = {}
            reserved_run_keys: set[str] = set()
            source_run_keys = {item[0]["runKey"] for item in staged_items}
            for item, listed in staged_items:
                source_run_key = item["runKey"]
                run_key = run_key_map.get(source_run_key)
                if run_key is None:
                    existing = self._runs.get(source_run_key)
                    can_reuse_source_key = source_run_key not in self._prepared
                    if existing is None and can_reuse_source_key:
                        run_key = source_run_key
                    elif (
                        existing is not None
                        and existing.owner_session_key == owner_session_key
                        and existing.owner_key == owner_key
                        and existing.ow_user_key == ow_user_key
                        and can_reuse_source_key
                    ):
                        run_key = source_run_key
                    else:
                        run_key = self._next_run_key(
                            reserved_run_keys | source_run_keys
                        )
                    run_key_map[source_run_key] = run_key
                    reserved_run_keys.add(run_key)
                if run_key != source_run_key:
                    item = {**item, "runKey": run_key}
                self._install_item(
                    item,
                    owner_session_key,
                    owner_key=owner_key,
                    ow_user_key=ow_user_key,
                    listed=listed,
                )
            self._seeded_contexts.add(seed_context)
        except BFFError:
            self._restore_state(snapshot)
            raise
        except Exception as exc:
            self._restore_state(snapshot)
            raise error_for("UPSTREAM_INVALID") from exc

    def _install_item(
        self,
        item: dict[str, Any],
        owner_session_key: str,
        *,
        owner_key: str,
        ow_user_key: str | None,
        listed: bool,
    ) -> None:
        run_key = item["runKey"]
        existing = self._runs.get(run_key)
        if existing is not None and (
            existing.owner_session_key != owner_session_key
            or existing.owner_key != owner_key
            or existing.ow_user_key != ow_user_key
        ):
            return
        if existing is not None and existing.idempotency_key is not None:
            return
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
            owner_key=owner_key,
            ow_user_key=ow_user_key,
        )
        self._runs[record.run_key] = record
        self._next_number = max(self._next_number, self._key_number(record.run_key) + 1)

    @staticmethod
    def _key_number(run_key: str) -> int:
        try:
            return int(run_key.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            return 0

    def get(
        self,
        run_key: str,
        owner_session_key: str,
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> RunRecord | None:
        record = self._runs.get(run_key)
        if (
            record is None
            or record.owner_session_key != owner_session_key
            or record.owner_key != owner_key
            or record.ow_user_key != ow_user_key
        ):
            return None
        return record

    @property
    def is_empty(self) -> bool:
        return not self._runs

    def is_seeded(
        self,
        owner_session_key: str,
        owner_key: str,
        ow_user_key: str | None = None,
    ) -> bool:
        return (owner_session_key, owner_key, ow_user_key) in self._seeded_contexts

    def has_foreign_run(
        self,
        run_key: str,
        owner_session_key: str,
        owner_key: str | None,
        ow_user_key: str | None,
    ) -> bool:
        record = self._runs.get(run_key)
        return record is not None and (
            record.owner_session_key != owner_session_key
            or record.owner_key != owner_key
            or record.ow_user_key != ow_user_key
        )

    def _next_run_key(self, reserved: set[str] | None = None) -> str:
        reserved = reserved or set()
        number = self._next_number
        while (
            f"verify-demo-{number:02d}" in self._runs
            or f"verify-demo-{number:02d}" in self._prepared
            or f"verify-demo-{number:02d}" in reserved
        ):
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
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> tuple[RunRecord, bool]:
        normalized_domains = _normalize_domains(domains)
        scope = (scope_date, scope_timezone, normalized_domains)
        idempotency_index = (
            owner_session_key,
            owner_key,
            ow_user_key,
            idempotency_key,
        )
        previous = self._idempotency.get(idempotency_index)
        if previous is not None:
            previous_scope, previous_key = previous
            if previous_scope != scope:
                raise error_for("IDEMPOTENCY_CONFLICT")
            return (
                self._validated_replay(
                    run_key=previous_key,
                    owner_session_key=owner_session_key,
                    owner_key=owner_key,
                    ow_user_key=ow_user_key,
                    scope=scope,
                ),
                False,
            )

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
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            idempotency_key=idempotency_key,
        )
        self._prepared[record.run_key] = record
        self._prepared_requests[record.run_key] = (
            owner_session_key,
            owner_key,
            ow_user_key,
            idempotency_key,
            scope,
        )
        return record, True

    def commit_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: RunRecord,
        scope_date: str,
        scope_timezone: str,
        domains: tuple[str, ...],
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> None:
        scope = (scope_date, scope_timezone, _normalize_domains(domains))
        self._validate_prepared_record(
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            idempotency_key=idempotency_key,
            scope=scope,
            record=record,
            require_prepared=True,
        )
        idempotency_index = (
            owner_session_key,
            owner_key,
            ow_user_key,
            idempotency_key,
        )
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
            del self._prepared[record.run_key]
            del self._prepared_requests[record.run_key]
        except Exception:
            self._restore_state(snapshot)
            self._prepared.pop(record.run_key, None)
            self._prepared_requests.pop(record.run_key, None)
            raise

    def _validate_prepared_record(
        self,
        *,
        owner_session_key: str,
        owner_key: str | None,
        ow_user_key: str | None,
        idempotency_key: str,
        scope: CreateScope,
        record: RunRecord,
        require_prepared: bool,
    ) -> None:
        if not isinstance(record, RunRecord):
            raise error_for("IDEMPOTENCY_CONFLICT")
        prepared_record = self._prepared.get(record.run_key)
        stored_record = self._runs.get(record.run_key)
        prepared = prepared_record is not None
        stored = stored_record is not None
        if (require_prepared and prepared_record is not record) or (
            not require_prepared and not (prepared or stored)
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")
        request = (owner_session_key, owner_key, ow_user_key, idempotency_key, scope)
        canonical = prepared_record if prepared else stored_record
        if canonical is None:
            raise error_for("IDEMPOTENCY_CONFLICT")
        if prepared and self._prepared_requests.get(record.run_key) != request:
            raise error_for("IDEMPOTENCY_CONFLICT")
        if not self._record_matches_request(
            record=canonical,
            run_key=record.run_key,
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            idempotency_key=idempotency_key,
            scope=scope,
        ) or not self._record_matches_request(
            record=record,
            run_key=record.run_key,
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            idempotency_key=idempotency_key,
            scope=scope,
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")

    @staticmethod
    def _record_matches_request(
        *,
        record: RunRecord,
        run_key: str,
        owner_session_key: str,
        owner_key: str | None,
        ow_user_key: str | None,
        idempotency_key: str,
        scope: CreateScope,
    ) -> bool:
        return (
            record.run_key == run_key
            and record.owner_session_key == owner_session_key
            and record.owner_key == owner_key
            and record.ow_user_key == ow_user_key
            and record.idempotency_key == idempotency_key
            and record.idempotency_scope() == scope
            and record.state == "pending"
            and record.listed is True
        )

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
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> tuple[RunRecord, bool]:
        record, created = self.prepare_create(
            owner_session_key=owner_session_key,
            scope_date=scope_date,
            scope_timezone=scope_timezone,
            domains=domains,
            idempotency_key=idempotency_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
        )
        if created:
            self.commit_create(
                owner_session_key=owner_session_key,
                idempotency_key=idempotency_key,
                record=record,
                scope_date=scope_date,
                scope_timezone=scope_timezone,
                domains=domains,
                owner_key=owner_key,
                ow_user_key=ow_user_key,
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
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> RunRecord | None:
        """Resolve an existing key without changing control-plane state."""

        previous = self._idempotency.get(
            (owner_session_key, owner_key, ow_user_key, idempotency_key)
        )
        if previous is None:
            return None
        previous_scope, previous_key = previous
        if previous_scope != (
            scope_date,
            scope_timezone,
            _normalize_domains(domains),
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")
        return self._validated_replay(
            run_key=previous_key,
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            scope=(scope_date, scope_timezone, _normalize_domains(domains)),
        )

    def _validated_replay(
        self,
        *,
        run_key: str,
        owner_session_key: str,
        owner_key: str | None,
        ow_user_key: str | None,
        scope: CreateScope,
    ) -> RunRecord:
        record = self._runs.get(run_key)
        if (
            record is None
            or record.owner_session_key != owner_session_key
            or record.owner_key != owner_key
            or record.ow_user_key != ow_user_key
            or record.idempotency_scope() != scope
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")
        return record

    def rollback_create(
        self,
        *,
        owner_session_key: str,
        idempotency_key: str,
        record: RunRecord,
        scope_date: str,
        scope_timezone: str,
        domains: tuple[str, ...],
        owner_key: str | None = None,
        ow_user_key: str | None = None,
    ) -> None:
        """Remove a newly-created record when boundary validation fails."""

        scope = (scope_date, scope_timezone, _normalize_domains(domains))
        self._validate_prepared_record(
            owner_session_key=owner_session_key,
            owner_key=owner_key,
            ow_user_key=ow_user_key,
            idempotency_key=idempotency_key,
            scope=scope,
            record=record,
            require_prepared=False,
        )
        idempotency_index = (
            owner_session_key,
            owner_key,
            ow_user_key,
            idempotency_key,
        )
        mapping = self._idempotency.get(idempotency_index)
        if mapping is not None and mapping != (scope, record.run_key):
            raise error_for("IDEMPOTENCY_CONFLICT")
        if self._runs.get(record.run_key) is not None and mapping is None:
            raise error_for("IDEMPOTENCY_CONFLICT")
        if any(
            key != idempotency_index and value[1] == record.run_key
            for key, value in self._idempotency.items()
        ):
            raise error_for("IDEMPOTENCY_CONFLICT")

        snapshot = self._snapshot_state()
        try:
            self._runs.pop(record.run_key, None)
            self._prepared.pop(record.run_key, None)
            self._prepared_requests.pop(record.run_key, None)
            self._idempotency.pop(idempotency_index, None)
            for cursor_key, cursor in list(self._cursors.items()):
                if record.run_key in cursor.run_keys:
                    self._cursors.pop(cursor_key, None)
        except Exception:
            self._restore_state(snapshot)
            raise

    def _filtered(
        self,
        *,
        owner_session_key: str,
        from_date: date | None,
        to_date: date | None,
        state: str | None,
        timezone_name: str,
        owner_key: str | None,
        ow_user_key: str | None,
    ) -> list[RunRecord]:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(timezone_name)
        records = [
            record
            for record in self._runs.values()
            if record.owner_session_key == owner_session_key
            and record.owner_key == owner_key
            and record.ow_user_key == ow_user_key
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
            owner_key=context.owner_key,
            ow_user_key=context.ow_user_key,
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
