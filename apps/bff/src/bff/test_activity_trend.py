from __future__ import annotations

from datetime import date

from bff.serializers import serialize_activity_trend
from bff.service import (
    aggregate_activity_trend,
    local_activity_trend_window,
    local_trend_window,
)


def row(day: str, *, steps: int | None, distance: float | None, source: str = "a"):
    return {
        "date": day,
        "source": {"provider": "provider-demo", "source": f"source-demo-{source}"},
        "steps": steps,
        "distance_meters": distance,
    }


def test_activity_trend_window_is_inclusive_end_date_and_timezone_aware() -> None:
    start, end = local_activity_trend_window(date(2024, 1, 2), "America/New_York")
    assert start == "2023-12-27T05:00:00Z"
    assert end == "2024-01-03T05:00:00Z"


def test_activity_trend_preserves_absent_null_zero_and_ambiguous_days() -> None:
    result = aggregate_activity_trend(
        date(2024, 1, 7),
        [
            row("2024-01-01", steps=100, distance=10),
            row("2024-01-02", steps=0, distance=0),
            row("2024-01-03", steps=None, distance=None),
            row("2024-01-04", steps=50, distance=5),
            row("2024-01-04", steps=60, distance=6, source="b"),
        ],
        timezone_name="UTC",
    )

    points = {point["date"]: point for point in result["points"]}
    assert points["2024-01-02"]["steps"]["state"] == "zero"
    assert points["2024-01-03"]["steps"]["state"] == "null"
    assert points["2024-01-05"]["steps"]["state"] == "empty"
    assert points["2024-01-04"]["steps"]["state"] == "inconclusive"
    assert result["steps"]["totalObserved"] == 100
    assert result["steps"]["observedDays"] == 2
    assert result["coverage"]["isPartial"] is True
    assert {warning["code"] for warning in result["warnings"]} == {
        "PARTIAL_COVERAGE",
        "INCONCLUSIVE",
    }


def test_activity_trend_keeps_numeric_points_as_values_when_window_is_partial() -> None:
    result = aggregate_activity_trend(
        date(2024, 1, 7),
        [
            row("2024-01-05", steps=1200, distance=None),
            row("2024-01-06", steps=0, distance=None),
        ],
        timezone_name="UTC",
    )

    points = {point["date"]: point for point in result["points"]}
    assert points["2024-01-05"]["steps"] == {
        "state": "value",
        "value": 1200,
        "unit": "count",
    }
    assert points["2024-01-06"]["steps"]["state"] == "zero"
    assert points["2024-01-06"]["steps"]["value"] == 0
    assert result["steps"]["totalObserved"] == 1200
    assert result["steps"]["averageObserved"] == 600
    assert result["steps"]["observedDays"] == 2
    assert "PARTIAL_COVERAGE" in {warning["code"] for warning in result["warnings"]}


def test_activity_trend_serializer_preserves_numeric_point_state() -> None:
    data = aggregate_activity_trend(
        date(2024, 1, 7),
        [row("2024-01-05", steps=1200, distance=10)],
        timezone_name="UTC",
    )
    response = {
        "schemaVersion": "1",
        "asOf": "2024-01-07T12:30:00Z",
        "timezone": "UTC",
        "data": {
            key: value
            for key, value in data.items()
            if key not in {"coverage", "warnings"}
        },
        "coverage": data["coverage"],
        "warnings": data["warnings"],
        "extensions": {},
    }

    serialized = serialize_activity_trend(
        response,
        logical_date="2024-01-07",
        timezone_name="UTC",
        from_utc="2024-01-01T00:00:00Z",
        to_utc="2024-01-08T00:00:00Z",
    )
    point = next(
        item for item in serialized["data"]["points"] if item["date"] == "2024-01-05"
    )
    assert point["steps"] == {"state": "value", "value": 1200, "unit": "count"}


def test_activity_trend_rejects_duplicate_date_without_aggregation() -> None:
    result = aggregate_activity_trend(
        date(2024, 1, 7),
        [row(f"2024-01-0{day}", steps=day, distance=day) for day in range(1, 8)]
        + [row("2024-01-04", steps=999, distance=999)],
        timezone_name="UTC",
    )

    point = next(item for item in result["points"] if item["date"] == "2024-01-04")
    assert point["steps"]["state"] == "inconclusive"
    assert point["steps"]["value"] is None
    assert result["steps"]["totalObserved"] == 24
    assert result["steps"]["averageObserved"] == 4


def test_activity_trend_rejects_mixed_sources_across_window() -> None:
    rows = [row(f"2024-01-0{day}", steps=day, distance=day) for day in range(1, 8)]
    rows[0] = row("2024-01-01", steps=1, distance=1, source="b")

    result = aggregate_activity_trend(date(2024, 1, 7), rows, timezone_name="UTC")

    points = {point["date"]: point for point in result["points"]}
    assert points["2024-01-01"]["steps"]["state"] == "value"
    assert points["2024-01-04"]["steps"]["state"] == "value"
    assert points["2024-01-02"]["steps"]["state"] == "value"
    assert result["steps"]["totalObserved"] is None
    assert result["distanceMeters"]["averageObserved"] is None
    assert "SOURCE_AMBIGUOUS" in {warning["code"] for warning in result["warnings"]}


def test_activity_trend_keeps_dst_window_boundaries() -> None:
    start, end = local_activity_trend_window(date(2024, 3, 10), "America/New_York")
    assert start == "2024-03-04T05:00:00Z"
    assert end == "2024-03-11T04:00:00Z"


def test_activity_trend_windows_are_range_specific_and_calendar_aware() -> None:
    assert local_trend_window(date(2024, 2, 29), "daily", "America/New_York") == (
        "2024-02-29T05:00:00Z",
        "2024-03-01T05:00:00Z",
    )
    assert local_trend_window(date(2024, 2, 29), "monthly", "UTC") == (
        "2024-02-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
    )
    assert local_trend_window(date(2024, 2, 29), "annual", "UTC") == (
        "2024-01-01T00:00:00Z",
        "2025-01-01T00:00:00Z",
    )


def test_activity_trend_monthly_uses_calendar_month_and_daily_points() -> None:
    result = aggregate_activity_trend(
        date(2024, 2, 29),
        [
            row("2024-02-01", steps=100, distance=10),
            row("2024-02-29", steps=200, distance=20),
        ],
        timezone_name="UTC",
        range_name="monthly",
    )

    assert result["range"] == "monthly"
    assert len(result["points"]) == 29
    assert result["points"][0]["steps"] == {
        "state": "value",
        "value": 100,
        "unit": "count",
    }
    assert result["coverage"]["expectedDays"] == 29
    assert result["coverage"]["availableDays"] == 2


def test_activity_trend_long_ranges_use_calendar_month_buckets() -> None:
    result = aggregate_activity_trend(
        date(2024, 8, 20),
        [
            row("2024-07-01", steps=100, distance=10),
            row("2024-08-20", steps=0, distance=0),
        ],
        timezone_name="UTC",
        range_name="180d",
    )

    assert result["range"] == "180d"
    assert result["points"][-1]["date"] == "2024-08-01"
    assert result["points"][-1]["steps"]["state"] == "zero"
    assert result["points"][-2]["steps"]["value"] == 100
    assert result["steps"]["expectedDays"] == 180


def test_activity_trend_annual_returns_all_leap_year_months() -> None:
    result = aggregate_activity_trend(
        date(2024, 12, 31),
        [
            row("2024-02-29", steps=200, distance=20),
            row("2024-12-31", steps=1200, distance=120),
        ],
        timezone_name="UTC",
        range_name="annual",
    )

    assert [point["date"] for point in result["points"]] == [
        f"2024-{month:02d}-01" for month in range(1, 13)
    ]
    assert len(result["points"]) == 12
    assert result["points"][1]["steps"]["value"] == 200
    assert result["points"][1]["steps"]["state"] == "value"
    assert result["points"][0]["steps"]["state"] == "empty"
    assert result["points"][11]["steps"]["value"] == 1200
    assert result["steps"]["expectedDays"] == 366


def test_activity_trend_180d_includes_boundary_months_and_labels_partial_buckets() -> (
    None
):
    result = aggregate_activity_trend(
        date(2024, 8, 20),
        [
            row("2024-02-23", steps=10, distance=1),
            row("2024-02-24", steps=20, distance=2),
            row("2024-08-20", steps=30, distance=3),
        ],
        timezone_name="UTC",
        range_name="180d",
    )

    assert [point["date"] for point in result["points"]] == [
        "2024-02-01",
        "2024-03-01",
        "2024-04-01",
        "2024-05-01",
        "2024-06-01",
        "2024-07-01",
        "2024-08-01",
    ]
    assert result["points"][0]["steps"]["value"] == 30
    assert result["points"][-1]["steps"]["value"] == 30
    assert result["steps"]["expectedDays"] == 180


def test_activity_trend_empty_window_is_not_partial() -> None:
    result = aggregate_activity_trend(
        date(2026, 8, 3),
        [],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["coverage"] == {
        "expectedDays": 1,
        "availableDays": 0,
        "isPartial": False,
    }
    assert result["points"][0]["steps"]["state"] == "empty"
