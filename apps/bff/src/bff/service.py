from __future__ import annotations

import math
import re
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapter.offline import FixtureContractError, OfflineFixtureAdapter

from .config import Settings
from .errors import ErrorCode, error_for
from .models import CreateRunBody
from .ranges import TREND_RANGES, trend_date_scope
from .serializers import (
    serialize_activity_trend,
    serialize_overview,
    serialize_run_create,
    serialize_run_detail,
    serialize_run_list,
    serialize_session,
    serialize_settings,
    serialize_sleep_trend,
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
DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"
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

    def get_ow_response(self, case: str) -> dict[str, Any]:
        return self.adapter.get_ow_response(case)


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


def local_activity_trend_window(
    logical_date: date_type, timezone_name: str
) -> tuple[str, str]:
    return local_trend_window(logical_date, "7d", timezone_name)


def local_trend_window(
    logical_date: date_type, range_name: str, timezone_name: str
) -> tuple[str, str]:
    start_date, end_date, _ = trend_date_scope(logical_date, range_name)
    start, _ = local_midnight_window(start_date, timezone_name)
    _, end = local_midnight_window(end_date, timezone_name)
    return start, end


def aggregate_activity_trend(
    logical_date: date_type,
    rows: list[dict[str, Any]],
    *,
    timezone_name: str,
    range_name: str = "7d",
) -> dict[str, Any]:
    if range_name not in TREND_RANGES:
        raise error_for("INVALID_QUERY", field="range")
    start_date, end_date, expected_labels = trend_date_scope(logical_date, range_name)
    dates = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]
    expected_dates = {item.isoformat() for item in dates}
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("date") in expected_dates:
            by_date.setdefault(row["date"], []).append(row)
    duplicate_dates = {day for day, items in by_date.items() if len(items) > 1}
    non_duplicate_source_keys = {
        row.get("source", {}).get("source")
        for day, items in by_date.items()
        if day not in duplicate_dates
        for row in items
        if isinstance(row.get("source"), dict)
        and row.get("source", {}).get("source") is not None
    }

    def metric(items: list[dict[str, Any]], field: str, unit: str) -> dict[str, Any]:
        if not items:
            return {"state": "empty", "value": None, "unit": None}
        if len(items) != 1:
            state = (
                "inconclusive"
                if items[0].get("date") in duplicate_dates
                else "source_ambiguous"
            )
            return {"state": state, "value": None, "unit": None}
        value = items[0].get(field)
        return {
            "state": "null" if value is None else "zero" if value == 0 else "value",
            "value": value,
            "unit": None if value is None else unit,
        }

    daily_points = [
        {
            "date": item.isoformat(),
            "steps": metric(by_date.get(item.isoformat(), []), "steps", "count"),
            "distanceMeters": metric(
                by_date.get(item.isoformat(), []), "distance_meters", "meters"
            ),
        }
        for item in dates
    ]

    def summary(
        field: str, unit: str, point_values: list[dict[str, Any]], expected_days: int
    ) -> dict[str, Any]:
        if len(non_duplicate_source_keys) > 1:
            return {
                "unit": unit,
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": expected_days,
            }
        values = [
            point[field]["value"]
            for point in point_values
            if point[field]["state"] in {"value", "zero", "partial"}
        ]
        return {
            "unit": unit,
            "totalObserved": sum(values) if values else None,
            "averageObserved": sum(values) / len(values) if values else None,
            "observedDays": len(values),
            "expectedDays": expected_days,
        }

    def bucket_points() -> list[dict[str, Any]]:
        if range_name in {"daily", "7d", "monthly"}:
            return daily_points
        buckets: dict[str, list[dict[str, Any]]] = {
            label: [] for label in expected_labels
        }
        for point in daily_points:
            buckets.setdefault(point["date"][:7] + "-01", []).append(point)

        def bucket_metric(
            items: list[dict[str, Any]], field: str, unit: str
        ) -> dict[str, Any]:
            states = [item[field]["state"] for item in items]
            if "inconclusive" in states:
                return {"state": "inconclusive", "value": None, "unit": None}
            if "source_ambiguous" in states:
                return {"state": "source_ambiguous", "value": None, "unit": None}
            values = [
                item[field]["value"]
                for item in items
                if item[field]["state"] in {"value", "zero", "partial"}
                and item[field]["value"] is not None
            ]
            if not values:
                return {
                    "state": "null" if "null" in states else "empty",
                    "value": None,
                    "unit": None,
                }
            total = sum(values)
            return {
                "state": (
                    "zero"
                    if total == 0
                    and all(
                        item[field]["state"] == "zero"
                        for item in items
                        if item[field]["state"] != "empty"
                    )
                    else "value"
                ),
                "value": total,
                "unit": unit,
            }

        return [
            {
                "date": bucket,
                "steps": bucket_metric(items, "steps", "count"),
                "distanceMeters": bucket_metric(items, "distanceMeters", "meters"),
            }
            for bucket, items in buckets.items()
        ]

    points = (
        daily_points if range_name in {"daily", "7d", "monthly"} else bucket_points()
    )
    expected_days = (end_date - start_date).days + 1

    ambiguous = any(
        point[name]["state"] == "source_ambiguous"
        for point in points
        for name in ("steps", "distanceMeters")
    )
    complete = all(
        point[name]["state"] in {"value", "zero"}
        for point in points
        for name in ("steps", "distanceMeters")
    )
    warnings = []
    if not complete:
        warnings.append(
            {
                "code": "PARTIAL_COVERAGE",
                "severity": "warning",
                "message": "La ventana no se pudo cerrar por completo.",
                "domain": "activity",
            }
        )
    if ambiguous:
        warnings.append(
            {
                "code": "SOURCE_AMBIGUOUS",
                "severity": "warning",
                "message": "La atribución requiere una regla adicional.",
                "domain": "activity",
            }
        )
    if len(non_duplicate_source_keys) > 1:
        warnings.append(
            {
                "code": "SOURCE_AMBIGUOUS",
                "severity": "warning",
                "message": "La ventana contiene más de una fuente observada.",
                "domain": "activity",
            }
        )
    if any(
        point[name]["state"] == "inconclusive"
        for point in points
        for name in ("steps", "distanceMeters")
    ):
        warnings.append(
            {
                "code": "INCONCLUSIVE",
                "severity": "warning",
                "message": "La ventana contiene fechas no únicas.",
                "domain": "activity",
            }
        )
    available_days = sum(
        1
        for point in points
        if any(point[name]["state"] != "empty" for name in ("steps", "distanceMeters"))
    )
    return {
        "logicalDate": logical_date.isoformat(),
        "range": range_name,
        # Aggregated buckets are for display; totals and averages remain based
        # on the canonical observed daily summaries.
        "steps": summary("steps", "count", daily_points, expected_days),
        "distanceMeters": summary(
            "distanceMeters", "meters", daily_points, expected_days
        ),
        "points": points,
        "coverage": {
            "expectedDays": expected_days,
            "availableDays": available_days,
            # An observed-but-incomplete window is partial; an empty window is
            # complete with no observations.
            "isPartial": available_days > 0 and not complete,
        },
        "warnings": warnings,
        "bucketMode": "calendar-month" if range_name in {"180d", "annual"} else "daily",
    }


def aggregate_sleep_trend(
    logical_date: date_type,
    summaries: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    timezone_name: str,
    range_name: str = "7d",
) -> dict[str, Any]:
    if range_name not in TREND_RANGES:
        raise error_for("INVALID_QUERY", field="range")
    start_date, end_date, expected_labels = trend_date_scope(logical_date, range_name)
    dates = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]
    expected = {item.isoformat() for item in dates}
    allowed_interval_categories = {
        "sleeping",
        "awake",
        "light",
        "deep",
        "rem",
        "in_bed",
        "unknown",
    }
    stage_fields = {
        "awakeSeconds": "awake_minutes",
        "lightSeconds": "light_minutes",
        "deepSeconds": "deep_minutes",
        "remSeconds": "rem_minutes",
    }

    def event_timestamp(row: dict[str, Any], key: str) -> datetime | None:
        value = row.get(key)
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    summaries_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in summaries:
        if row.get("date") in expected:
            summaries_by_date.setdefault(row["date"], []).append(row)
    events_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        event_date = row.get("date")
        if event_date is None:
            end = event_timestamp(row, "end_time")
            if end is not None:
                event_date = end.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        if event_date in expected:
            events_by_date.setdefault(event_date, []).append(row)
    validated_intervals_by_date: dict[str, list[dict[str, Any]]] = {}
    duplicate_dates = {day for day, rows in summaries_by_date.items() if len(rows) > 1}
    all_rows = [
        row
        for rows in (*summaries_by_date.values(), *events_by_date.values())
        for row in rows
    ]
    sources = {
        (
            row.get("source", {}).get("provider"),
            row.get("source", {}).get("source"),
        )
        for row in all_rows
        if isinstance(row.get("source"), dict)
        and row.get("source", {}).get("provider")
        and row.get("source", {}).get("source")
    }

    def metric(value: Any, unit: str, *, state: str | None = None) -> dict[str, Any]:
        if state is not None:
            return {"state": state, "value": None, "unit": None}
        if value is None:
            return {"state": "null", "value": None, "unit": None}
        return {
            "state": "zero" if value == 0 else "value",
            "value": value,
            "unit": unit,
        }

    def unsupported() -> dict[str, Any]:
        return metric(None, "seconds", state="unsupported")

    def event_seconds(row: dict[str, Any]) -> int | None:
        value = row.get("sleep_duration_seconds")
        return value if type(value) is int and value >= 0 else None

    def valid_event(row: dict[str, Any]) -> bool:
        start = event_timestamp(row, "start_time")
        end = event_timestamp(row, "end_time")
        return start is not None and end is not None and end > start

    def validated_intervals(
        row: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], bool]:
        raw = row.get("sleep_stage_intervals")
        if raw is None:
            return [], row.get("is_nap") is not True
        if not isinstance(raw, list):
            return [], True
        event_start = event_timestamp(row, "start_time")
        event_end = event_timestamp(row, "end_time")
        if event_start is None or event_end is None:
            return [], True
        result: list[dict[str, Any]] = []
        for interval in raw:
            if not isinstance(interval, dict):
                return [], True
            start = event_timestamp(interval, "start_time")
            end = event_timestamp(interval, "end_time")
            category = interval.get("stage")
            if (
                start is None
                or end is None
                or end <= start
                or start < event_start
                or end > event_end
                or category not in allowed_interval_categories
            ):
                return [], True
            result.append(
                {
                    "start": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "category": category,
                    "isNap": row.get("is_nap") is True,
                    "_sort": start,
                }
            )
        result.sort(key=lambda item: item["_sort"])
        if any(
            result[index]["_sort"]
            < datetime.fromisoformat(result[index - 1]["end"].replace("Z", "+00:00"))
            for index in range(1, len(result))
        ):
            return [], True
        declared_sleep_seconds = event_seconds(row)
        if declared_sleep_seconds is None:
            return [], True
        covered_sleep = sum(
            (
                datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))
                - interval["_sort"]
                for interval in result
                if interval["category"] in {"sleeping", "light", "deep", "rem"}
            ),
            timedelta(),
        )
        if covered_sleep != timedelta(seconds=declared_sleep_seconds):
            return [], True
        return result, False

    def stage_metrics(
        row: dict[str, Any] | None, sleep_events: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        summary_stages = row.get("stages") if row else None
        if summary_stages is not None and not isinstance(summary_stages, dict):
            return {
                name: metric(None, "seconds", state="inconclusive")
                for name in stage_fields
            }, True
        event_totals = {name: 0 for name in stage_fields}
        observed_event_stages: set[str] = set()
        invalid = False
        for sleep_event in sleep_events:
            intervals, interval_invalid = validated_intervals(sleep_event)
            invalid = invalid or interval_invalid
            if sleep_event.get("is_nap") is True:
                continue
            for interval in intervals:
                output_name = next(
                    (
                        name
                        for name, input_name in stage_fields.items()
                        if interval["category"] == input_name.removesuffix("_minutes")
                    ),
                    None,
                )
                if output_name is None:
                    continue
                observed_event_stages.add(output_name)
                event_totals[output_name] += int(
                    (
                        datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))
                        - interval["_sort"]
                    ).total_seconds()
                )
        if invalid:
            return {
                name: metric(None, "seconds", state="inconclusive")
                for name in stage_fields
            }, True
        result: dict[str, dict[str, Any]] = {}
        for output_name, input_name in stage_fields.items():
            if isinstance(summary_stages, dict) and input_name in summary_stages:
                minutes = summary_stages[input_name]
                seconds = None if minutes is None else minutes * 60
                if (
                    minutes is not None
                    and (
                        type(minutes) not in {int, float}
                        or not math.isfinite(minutes)
                        or minutes < 0
                        or not float(seconds).is_integer()
                    )
                ):
                    return {
                        name: metric(None, "seconds", state="inconclusive")
                        for name in stage_fields
                    }, True
                value = None if seconds is None else int(seconds)
                result[output_name] = metric(value, "seconds")
            elif output_name in observed_event_stages:
                result[output_name] = metric(event_totals[output_name], "seconds")
            else:
                result[output_name] = unsupported()
        return result, False

    def overlaps(rows: list[dict[str, Any]]) -> bool:
        intervals = []
        for row in rows:
            try:
                start = datetime.fromisoformat(
                    str(row["start_time"]).replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    str(row["end_time"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError):
                return True
            if end <= start or start.tzinfo is None or end.tzinfo is None:
                return True
            intervals.append((start, end))
        intervals.sort()
        return any(
            intervals[index][0] < intervals[index - 1][1]
            for index in range(1, len(intervals))
        )

    def point(day: date_type) -> dict[str, Any]:
        label = day.isoformat()
        rows = summaries_by_date.get(label, [])
        sleep_events = events_by_date.get(label, [])
        day_rows = rows + sleep_events
        event_intervals = [validated_intervals(item) for item in sleep_events]
        complete_intervals = [
            interval
            for intervals, _invalid in event_intervals
            for interval in intervals
        ]
        complete_intervals.sort(key=lambda item: item["_sort"])
        intervals_overlap = any(
            complete_intervals[index]["_sort"]
            < datetime.fromisoformat(
                complete_intervals[index - 1]["end"].replace("Z", "+00:00")
            )
            for index in range(1, len(complete_intervals))
        )
        source_identities = [
            (
                (
                    item.get("source", {}).get("provider"),
                    item.get("source", {}).get("source"),
                )
                if isinstance(item.get("source"), dict)
                else (None, None)
            )
            for item in day_rows
        ]
        if len(rows) > 1:
            state = "inconclusive"
        elif any(not provider or not source for provider, source in source_identities):
            state = "inconclusive"
        elif len(set(source_identities)) > 1:
            state = "source_ambiguous"
        elif any(type(item.get("is_nap")) is not bool for item in sleep_events):
            state = "inconclusive"
        elif any(not valid_event(item) for item in sleep_events):
            state = "inconclusive"
        elif overlaps(sleep_events):
            state = "inconclusive"
        elif any(invalid for _intervals, invalid in event_intervals):
            state = "inconclusive"
        elif intervals_overlap:
            state = "inconclusive"
        else:
            state = None
        stages, invalid_stages = stage_metrics(
            rows[0] if len(rows) == 1 else None, sleep_events
        )
        if invalid_stages:
            state = "inconclusive"
        if state:
            empty = metric(None, "seconds", state=state)
            return {
                "date": label,
                "nightSleepSeconds": empty,
                "napsSeconds": metric(None, "seconds", state=state),
                "unclassifiedSeconds": metric(None, "seconds", state=state),
                "stages": {
                    name: (
                        stages[name]
                        if invalid_stages
                        else metric(None, "seconds", state=state)
                    )
                    for name in stage_fields
                },
                "bedtime": None,
                "wakeTime": None,
            }
        row = rows[0] if rows else None
        if (
            row
            and (row.get("start_time") is not None or row.get("end_time") is not None)
            and (
                event_timestamp(row, "start_time") is None
                or event_timestamp(row, "end_time") is None
                or event_timestamp(row, "end_time")
                <= event_timestamp(row, "start_time")
            )
        ):
            state = "inconclusive"
        if state:
            empty = metric(None, "seconds", state=state)
            return {
                "date": label,
                "nightSleepSeconds": empty,
                "napsSeconds": metric(None, "seconds", state=state),
                "unclassifiedSeconds": metric(None, "seconds", state=state),
                "stages": {
                    name: metric(None, "seconds", state=state) for name in stage_fields
                },
                "bedtime": None,
                "wakeTime": None,
            }
        validated_intervals_by_date[label] = complete_intervals
        night_value = (
            row.get("sleep_duration_seconds")
            if row
            and type(row.get("sleep_duration_seconds")) is int
            and row.get("sleep_duration_seconds") >= 0
            else None
        )
        if night_value is None and row:
            duration_minutes = row.get("duration_minutes")
            if (
                type(duration_minutes) in {int, float}
                and math.isfinite(duration_minutes)
                and duration_minutes >= 0
                and float(duration_minutes * 60).is_integer()
            ):
                night_value = int(duration_minutes * 60)
        if night_value is None:
            non_naps = [item for item in sleep_events if item.get("is_nap") is False]
            non_nap_values = [event_seconds(item) for item in non_naps]
            if non_naps and all(value is not None for value in non_nap_values):
                night_value = sum(
                    value for value in non_nap_values if value is not None
                )
        night = (
            metric(night_value, "seconds")
            if night_value is not None
            else metric(
                None,
                "seconds",
                state="empty" if not row and not sleep_events else "inconclusive",
            )
        )
        naps = [item for item in sleep_events if item.get("is_nap") is True]
        nap_values = [event_seconds(item) for item in naps]
        nap_metric = (
            metric(sum(nap_values), "seconds")
            if naps and all(value is not None for value in nap_values)
            else metric(None, "seconds", state="inconclusive" if naps else "empty")
        )
        if night["value"] is None:
            unclassified = metric(None, "seconds", state=night["state"])
        else:
            classified_seconds = sum(
                stages[name]["value"] or 0
                for name in ("lightSeconds", "deepSeconds", "remSeconds")
                if stages[name]["state"] in {"value", "zero"}
            )
            if classified_seconds > night["value"]:
                inconclusive = metric(None, "seconds", state="inconclusive")
                night = inconclusive
                unclassified = inconclusive
                stages = {name: inconclusive for name in stage_fields}
                validated_intervals_by_date[label] = []
            else:
                unclassified = metric(night["value"] - classified_seconds, "seconds")
        return {
            "date": label,
            "nightSleepSeconds": night,
            "napsSeconds": nap_metric,
            "unclassifiedSeconds": unclassified,
            "stages": stages,
            "bedtime": (
                (row or {}).get("start_time")
                if row and event_timestamp(row, "start_time") is not None
                else None
            ),
            "wakeTime": (
                (row or {}).get("end_time")
                if row and event_timestamp(row, "end_time") is not None
                else None
            ),
        }

    daily_points = [point(day) for day in dates]
    interval_candidates = [
        interval
        for day_intervals in validated_intervals_by_date.values()
        for interval in day_intervals
    ]
    intervals = sorted(interval_candidates, key=lambda item: item.pop("_sort"))
    if any(
        datetime.fromisoformat(intervals[index]["start"].replace("Z", "+00:00"))
        < datetime.fromisoformat(intervals[index - 1]["end"].replace("Z", "+00:00"))
        for index in range(1, len(intervals))
    ):
        intervals = []

    def circular_average(values: list[datetime]) -> str | None:
        if not values:
            return None
        local_values = [value.astimezone(ZoneInfo(timezone_name)) for value in values]
        angles = [
            ((value.hour * 3600 + value.minute * 60 + value.second) / 86400)
            * 2
            * math.pi
            for value in local_values
        ]
        sine = sum(math.sin(angle) for angle in angles) / len(angles)
        cosine = sum(math.cos(angle) for angle in angles) / len(angles)
        if abs(sine) < 1e-9 and abs(cosine) < 1e-9:
            return None
        seconds = math.atan2(sine, cosine) % (2 * math.pi)
        seconds = seconds / (2 * math.pi) * 86400
        if seconds >= 86399.5:
            seconds = 0
        base = datetime.combine(logical_date, time.min, tzinfo=ZoneInfo(timezone_name))
        averaged = (base + timedelta(seconds=seconds)).astimezone(timezone.utc)
        return averaged.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    bedtime_values = [
        parsed
        for row in summaries
        if row.get("date") in expected
        for parsed in [event_timestamp(row, "start_time")]
        if parsed is not None
    ]
    wake_values = [
        parsed
        for row in summaries
        if row.get("date") in expected
        for parsed in [event_timestamp(row, "end_time")]
        if parsed is not None
    ]
    values = {
        key: [
            item[key]["value"]
            for item in daily_points
            if item[key]["value"] is not None
            and item[key]["state"] in {"value", "zero"}
        ]
        for key in ("nightSleepSeconds", "napsSeconds")
    }
    for stage in stage_fields:
        values[stage] = [
            item["stages"][stage]["value"]
            for item in daily_points
            if item["stages"][stage]["value"] is not None
            and item["stages"][stage]["state"] in {"value", "zero"}
        ]

    def aggregate(key: str, unit: str = "seconds") -> dict[str, Any]:
        observed = values[key]
        if len(sources) > 1:
            return {
                "state": "source_ambiguous",
                "unit": unit,
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": len(observed),
                "expectedDays": len(dates),
            }
        return {
            "state": "value" if observed else "empty",
            "unit": unit,
            "totalObserved": sum(observed) if observed else None,
            "averageObserved": sum(observed) / len(observed) if observed else None,
            "observedDays": len(observed),
            "expectedDays": len(dates),
        }

    points = daily_points
    if range_name in {"180d", "annual"}:
        grouped = {label: [] for label in expected_labels}
        for item in daily_points:
            grouped.setdefault(item["date"][:7] + "-01", []).append(item)
        points = []
        for label, items in grouped.items():
            combined = {
                "date": label,
                "nightSleepSeconds": metric(None, "seconds", state="empty"),
                "napsSeconds": metric(None, "seconds", state="empty"),
                "unclassifiedSeconds": metric(None, "seconds", state="empty"),
                "stages": {name: unsupported() for name in stage_fields},
                "bedtime": None,
                "wakeTime": None,
            }
            for key in ("nightSleepSeconds", "napsSeconds"):
                states = {item[key]["state"] for item in items}
                if "inconclusive" in states or "source_ambiguous" in states:
                    combined[key] = metric(
                        None,
                        "seconds",
                        state=(
                            "inconclusive"
                            if "inconclusive" in states
                            else "source_ambiguous"
                        ),
                    )
                    continue
                vals = [
                    item[key]["value"]
                    for item in items
                    if item[key]["value"] is not None
                ]
                if vals:
                    combined[key] = metric(sum(vals), "seconds")
            unclassified_states = {
                item["unclassifiedSeconds"]["state"] for item in items
            }
            if (
                "inconclusive" in unclassified_states
                or "source_ambiguous" in unclassified_states
            ):
                combined["unclassifiedSeconds"] = metric(
                    None,
                    "seconds",
                    state=(
                        "inconclusive"
                        if "inconclusive" in unclassified_states
                        else "source_ambiguous"
                    ),
                )
            else:
                unclassified_values = [
                    item["unclassifiedSeconds"]["value"]
                    for item in items
                    if item["unclassifiedSeconds"]["value"] is not None
                ]
                if unclassified_values:
                    combined["unclassifiedSeconds"] = metric(
                        sum(unclassified_values), "seconds"
                    )
            for stage in stage_fields:
                states = {item["stages"][stage]["state"] for item in items}
                if "inconclusive" in states or "source_ambiguous" in states:
                    combined["stages"][stage] = metric(
                        None,
                        "seconds",
                        state=(
                            "inconclusive"
                            if "inconclusive" in states
                            else "source_ambiguous"
                        ),
                    )
                    continue
                vals = [
                    item["stages"][stage]["value"]
                    for item in items
                    if item["stages"][stage]["value"] is not None
                ]
                if vals:
                    combined["stages"][stage] = metric(sum(vals), "seconds")
            points.append(combined)
    incomplete = any(
        item["nightSleepSeconds"]["state"] not in {"value", "zero"}
        for item in daily_points
    )
    warnings = (
        [
            {
                "code": "PARTIAL_COVERAGE",
                "severity": "warning",
                "message": "La ventana no se pudo cerrar por completo.",
                "domain": "sleep",
            }
        ]
        if incomplete
        and any(values["nightSleepSeconds"] or values["napsSeconds"] for _ in [0])
        else []
    )
    if duplicate_dates:
        warnings.append(
            {
                "code": "INCONCLUSIVE",
                "severity": "warning",
                "message": "La ventana contiene fechas no únicas.",
                "domain": "sleep",
            }
        )
    if any(
        item["nightSleepSeconds"]["state"] == "inconclusive"
        or item["napsSeconds"]["state"] == "inconclusive"
        for item in daily_points
    ) and not any(warning["code"] == "INCONCLUSIVE" for warning in warnings):
        warnings.append(
            {
                "code": "INCONCLUSIVE",
                "severity": "warning",
                "message": "Los eventos de sueño no forman una cronología válida.",
                "domain": "sleep",
            }
        )
    if any(
        point["stages"][stage]["state"] == "inconclusive"
        for point in daily_points
        for stage in stage_fields
    ):
        warnings.append(
            {
                "code": "INCONCLUSIVE",
                "severity": "warning",
                "message": "Las etapas de sueño contienen intervalos contradictorios.",
                "domain": "sleep",
            }
        )
    if len(sources) > 1:
        warnings.append(
            {
                "code": "SOURCE_AMBIGUOUS",
                "severity": "warning",
                "message": "La atribución requiere una regla adicional.",
                "domain": "sleep",
            }
        )
    if any(
        item["napsSeconds"]["state"] in {"inconclusive", "source_ambiguous"}
        for item in daily_points
    ):
        warnings.append(
            {
                "code": "SOURCE_AMBIGUOUS",
                "severity": "warning",
                "message": "La atribución requiere una regla adicional.",
                "domain": "sleep",
            }
        )
    return {
        "logicalDate": logical_date.isoformat(),
        "range": range_name,
        **{
            key: aggregate(key)
            for key in (
                "nightSleepSeconds",
                "napsSeconds",
                "awakeSeconds",
                "lightSeconds",
                "deepSeconds",
                "remSeconds",
            )
        },
        "points": points,
        "bucketMode": "calendar-month" if range_name in {"180d", "annual"} else "daily",
        "observedDays": len(values["nightSleepSeconds"]),
        "coverage": {
            "expectedDays": len(dates),
            "availableDays": len(values["nightSleepSeconds"]),
            "isPartial": bool(warnings),
        },
        "warnings": warnings,
        "averageBedtime": (
            None if len(sources) > 1 else circular_average(bedtime_values)
        ),
        "averageWakeTime": None if len(sources) > 1 else circular_average(wake_values),
        "intervals": intervals if range_name == "daily" else [],
    }


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
        timezone_name = validate_timezone(timezone_value or DEFAULT_TIMEZONE)
        return logical_date, parsed_date, timezone_name

    def optional_context(
        self, date_value: str | None, timezone_value: str | None
    ) -> tuple[str, date_type, str]:
        if date_value is None:
            date_value = "2024-01-02"
        if timezone_value is None:
            timezone_value = DEFAULT_TIMEZONE
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

    def activity_trend(
        self,
        *,
        logical_date: str,
        parsed_date: date_type,
        timezone_name: str,
        range_name: str,
    ) -> dict[str, Any]:
        start, end = local_trend_window(parsed_date, range_name, timezone_name)
        getter = getattr(self.adapter, "get_activity_trend_response", None)
        if getter is not None:
            response = getter(
                logical_date=logical_date,
                timezone_name=timezone_name,
                start_utc=start,
                end_utc=end,
                range_name=range_name,
                owner_context=self._owner_context(),
            )
        else:
            rows = self.adapter.get_ow_response("activity_summary")["data"]
            data = aggregate_activity_trend(
                parsed_date, rows, timezone_name=timezone_name, range_name=range_name
            )
            coverage = data.pop("coverage")
            warnings = data.pop("warnings")
            response = {
                "schemaVersion": "1",
                "asOf": "2024-01-02T12:30:00Z",
                "timezone": timezone_name,
                "data": data,
                "coverage": coverage,
                "warnings": warnings,
                "extensions": {},
            }
        return serialize_activity_trend(
            response,
            logical_date=logical_date,
            timezone_name=timezone_name,
            from_utc=start,
            to_utc=end,
        )

    def sleep_trend(
        self,
        *,
        logical_date: str,
        parsed_date: date_type,
        timezone_name: str,
        range_name: str,
    ) -> dict[str, Any]:
        if range_name not in TREND_RANGES:
            raise error_for("INVALID_QUERY", field="range")
        start, end = local_trend_window(parsed_date, range_name, timezone_name)
        getter = getattr(self.adapter, "get_sleep_trend_response", None)
        if getter is not None:
            response = getter(
                logical_date=logical_date,
                timezone_name=timezone_name,
                start_utc=start,
                end_utc=end,
                range_name=range_name,
                owner_context=self._owner_context(),
            )
        else:
            summaries = self.adapter.get_ow_response("sleep_summary")["data"]
            events = self.adapter.get_ow_response("events_sleep")["data"]
            data = aggregate_sleep_trend(
                parsed_date,
                summaries,
                events,
                timezone_name=timezone_name,
                range_name=range_name,
            )
            response = {
                "schemaVersion": "1",
                "asOf": "2024-01-02T12:30:00Z",
                "timezone": timezone_name,
                "data": {
                    key: value
                    for key, value in data.items()
                    if key not in {"coverage", "warnings"}
                },
                "coverage": data["coverage"],
                "warnings": data["warnings"],
                "extensions": {},
            }
        return serialize_sleep_trend(
            response,
            logical_date=logical_date,
            timezone_name=timezone_name,
            from_utc=start,
            to_utc=end,
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
