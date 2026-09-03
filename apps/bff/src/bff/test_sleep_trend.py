from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from bff.errors import BFFError
from bff.serializers import serialize_sleep_trend
from bff.service import DEFAULT_TIMEZONE, aggregate_sleep_trend


def summary(
    day: str,
    *,
    duration: int | None,
    sleep_duration: int | None = None,
    stages: dict[str, int | None] | None = None,
):
    result = {
        "date": day,
        "source": {"provider": "provider-demo", "source": "source-demo-a"},
        "start_time": "2024-01-01T22:30:00Z" if duration is not None else None,
        "end_time": "2024-01-02T06:30:00Z" if duration is not None else None,
        "duration_minutes": duration,
        "sleep_duration_seconds": sleep_duration,
    }
    if stages is not None:
        result["stages"] = stages
    return result


def event(day: str, *, is_nap: bool | object, duration: int | None):
    return {
        "date": day,
        "start_time": "2024-01-02T13:00:00Z",
        "end_time": "2024-01-02T13:30:00Z",
        "duration_seconds": duration,
        "sleep_duration_seconds": duration,
        "is_nap": is_nap,
        "source": {"provider": "provider-demo", "source": "source-demo-a"},
    }


def test_sleep_trend_uses_sleep_seconds_and_keeps_naps_separate() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary("2024-01-01", duration=420, sleep_duration=25_200),
            summary("2024-01-02", duration=None),
        ],
        [
            event("2024-01-02", is_nap=True, duration=1_800),
        ],
        timezone_name="UTC",
        range_name="7d",
    )

    points = {item["date"]: item for item in result["points"]}
    assert points["2024-01-01"]["nightSleepSeconds"]["value"] == 25_200
    assert points["2024-01-02"]["napsSeconds"]["value"] == 1_800
    assert points["2024-01-01"]["stages"]["deepSeconds"]["state"] == "unsupported"
    assert points["2023-12-31"]["nightSleepSeconds"]["state"] == "empty"
    assert result["nightSleepSeconds"]["observedDays"] == 1
    assert result["coverage"]["isPartial"] is True


def test_sleep_trend_rejects_duplicate_dates_and_mixed_sources() -> None:
    duplicate = summary("2024-01-02", duration=420)
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [duplicate, {**duplicate, "duration_minutes": 430}],
        [],
        timezone_name="UTC",
        range_name="daily",
    )
    assert result["points"][0]["nightSleepSeconds"]["state"] == "inconclusive"
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_sleep_trend_rejects_overlapping_events_and_mixed_sources() -> None:
    first = event("2024-01-02", is_nap=True, duration=1_800)
    second = {
        **event("2024-01-02", is_nap=True, duration=1_800),
        "start_time": "2024-01-02T13:15:00Z",
    }
    other_source = {
        **event("2024-01-02", is_nap=True, duration=1_800),
        "source": {"provider": "provider-demo-b", "source": "source-demo-b"},
    }
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [first, second, other_source],
        timezone_name="UTC",
        range_name="daily",
    )
    assert result["points"][0]["napsSeconds"]["state"] == "source_ambiguous"
    assert {warning["code"] for warning in result["warnings"]} >= {"SOURCE_AMBIGUOUS"}


def test_duration_only_event_is_not_time_in_bed_sleep() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [
            {
                **event("2024-01-02", is_nap=False, duration=28_800),
                "sleep_duration_seconds": None,
            }
        ],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"]["state"] in {
        "inconclusive",
        "not_verifiable",
        "unsupported",
    }
    assert point["nightSleepSeconds"]["value"] is None


def test_summary_duration_minutes_is_sleep_not_time_in_bed() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            {
                **summary(
                    "2024-01-02",
                    duration=10,
                    sleep_duration=None,
                    stages={
                        "awake_minutes": 1,
                        "light_minutes": 4,
                        "deep_minutes": 3,
                        "rem_minutes": 3,
                    },
                ),
                "time_in_bed_minutes": 11,
            }
        ],
        [],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"]["value"] == 600
    assert point["stages"]["awakeSeconds"]["value"] == 60
    assert point["unclassifiedSeconds"]["value"] == 0


def test_sleep_events_without_logical_date_and_intervals_are_inconclusive() -> None:
    event_without_date = event("2024-01-02", is_nap=False, duration=25_200)
    event_without_date.pop("date")
    event_without_date.update(
        {
            "start_time": "2024-01-01T22:30:00Z",
            "end_time": "2024-01-02T06:30:00Z",
        }
    )

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [event_without_date],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["points"][0]["nightSleepSeconds"] == {
        "state": "inconclusive",
        "value": None,
        "unit": None,
    }
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_sleep_events_without_logical_date_retain_validated_intervals() -> None:
    event_without_date = {
        **event("2024-01-02", is_nap=False, duration=600),
        "start_time": "2024-01-01T23:50:00Z",
        "end_time": "2024-01-02T00:00:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-01T23:50:00Z",
                "end_time": "2024-01-02T00:00:00Z",
                "stage": "light",
            }
        ],
    }
    event_without_date.pop("date")

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [event_without_date],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["intervals"] == [
        {
            "start": "2024-01-01T23:50:00Z",
            "end": "2024-01-02T00:00:00Z",
            "category": "light",
            "isNap": False,
        }
    ]


def test_malformed_is_nap_does_not_become_night_or_nap() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [event("2024-01-02", is_nap="false", duration=1_800)],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"]["value"] is None
    assert point["napsSeconds"]["value"] is None
    assert point["nightSleepSeconds"]["state"] in {"inconclusive", "not_verifiable"}


def test_sleep_serializer_rejects_wrong_range_shape_and_invalid_timestamps() -> None:
    response = {
        "schemaVersion": "1",
        "asOf": "2024-01-02T12:30:00Z",
        "timezone": "UTC",
        "data": {
            "logicalDate": "2024-01-02",
            "range": "7d",
            "nightSleepSeconds": {
                "state": "value",
                "unit": "seconds",
                "totalObserved": 1,
                "averageObserved": 1,
                "observedDays": 1,
                "expectedDays": 1,
            },
            "napsSeconds": {
                "state": "empty",
                "unit": "seconds",
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": 1,
            },
            "awakeSeconds": {
                "state": "empty",
                "unit": "seconds",
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": 1,
            },
            "lightSeconds": {
                "state": "empty",
                "unit": "seconds",
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": 1,
            },
            "deepSeconds": {
                "state": "empty",
                "unit": "seconds",
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": 1,
            },
            "remSeconds": {
                "state": "empty",
                "unit": "seconds",
                "totalObserved": None,
                "averageObserved": None,
                "observedDays": 0,
                "expectedDays": 1,
            },
            "points": [
                {
                    "date": "2024-01-02",
                    "nightSleepSeconds": {
                        "state": "value",
                        "value": 1,
                        "unit": "seconds",
                    },
                    "napsSeconds": {"state": "empty", "value": None, "unit": None},
                    "stages": {
                        name: {"state": "unsupported", "value": None, "unit": None}
                        for name in (
                            "awakeSeconds",
                            "lightSeconds",
                            "deepSeconds",
                            "remSeconds",
                        )
                    },
                    "bedtime": "not-a-timestamp",
                    "wakeTime": None,
                }
            ],
            "bucketMode": "daily",
            "observedDays": 1,
        },
        "coverage": {"expectedDays": 1, "availableDays": 1, "isPartial": False},
        "warnings": [],
        "extensions": {},
    }

    import pytest

    with pytest.raises(BFFError):
        serialize_sleep_trend(
            response,
            logical_date="2024-01-02",
            timezone_name="UTC",
            from_utc="2024-01-02T00:00:00Z",
            to_utc="2024-01-03T00:00:00Z",
        )


@pytest.mark.parametrize(
    ("range_name", "logical_date", "expected_labels", "expected_days"),
    [
        (
            "monthly",
            date(2024, 2, 29),
            [f"2024-02-{day:02d}" for day in range(1, 30)],
            29,
        ),
        (
            "180d",
            date(2024, 5, 15),
            [
                "2023-11-01",
                "2023-12-01",
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
                "2024-04-01",
                "2024-05-01",
            ],
            180,
        ),
        (
            "annual",
            date(2024, 12, 31),
            [f"2024-{month:02d}-01" for month in range(1, 13)],
            366,
        ),
    ],
)
def test_sleep_trend_uses_conservative_calendar_buckets_and_empty_labels(
    range_name: str,
    logical_date: date,
    expected_labels: list[str],
    expected_days: int,
) -> None:
    result = aggregate_sleep_trend(
        logical_date,
        [summary("2024-02-29", duration=420, sleep_duration=25_200)],
        [],
        timezone_name="UTC",
        range_name=range_name,
    )

    assert result["bucketMode"] == (
        "calendar-month" if range_name in {"180d", "annual"} else "daily"
    )
    assert [point["date"] for point in result["points"]] == expected_labels
    assert result["coverage"]["expectedDays"] == expected_days
    observed_label = "2024-02-29" if range_name == "monthly" else "2024-02-01"
    observed = next(
        point for point in result["points"] if point["date"] == observed_label
    )
    assert observed["nightSleepSeconds"]["value"] == 25_200
    empty = next(
        point
        for point in result["points"]
        if point["date"] != "2024-02-01"
        and point["nightSleepSeconds"]["state"] == "empty"
    )
    assert empty["nightSleepSeconds"] == {"state": "empty", "value": None, "unit": None}


def test_sleep_trend_preserves_localized_bedtime_and_wake_timestamps() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            {
                **summary("2024-01-02", duration=420, sleep_duration=25_200),
                "start_time": "2024-01-01T22:30:00Z",
                "end_time": "2024-01-02T06:30:00Z",
            }
        ],
        [],
        timezone_name="Europe/Madrid",
        range_name="daily",
    )

    assert result["points"][0]["bedtime"] == "2024-01-01T22:30:00Z"
    assert result["points"][0]["wakeTime"] == "2024-01-02T06:30:00Z"


def test_default_timezone_is_explicitly_argentina_and_override_is_preserved() -> None:
    assert DEFAULT_TIMEZONE == "America/Argentina/Buenos_Aires"


def test_daily_sleep_exposes_validated_generic_intervals_in_order() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [
            {
                **event("2024-01-02", is_nap=False, duration=420),
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:12:00Z",
                "sleep_stage_intervals": [
                    {
                        "start_time": "2024-01-02T06:05:00Z",
                        "end_time": "2024-01-02T06:10:00Z",
                        "stage": "awake",
                    },
                    {
                        "start_time": "2024-01-02T06:00:00Z",
                        "end_time": "2024-01-02T06:05:00Z",
                        "stage": "sleeping",
                    },
                    {
                        "start_time": "2024-01-02T06:10:00Z",
                        "end_time": "2024-01-02T06:12:00Z",
                        "stage": "rem",
                    },
                ],
            }
        ],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["intervals"] == [
        {
            "start": "2024-01-02T06:00:00Z",
            "end": "2024-01-02T06:05:00Z",
            "category": "sleeping",
            "isNap": False,
        },
        {
            "start": "2024-01-02T06:05:00Z",
            "end": "2024-01-02T06:10:00Z",
            "category": "awake",
            "isNap": False,
        },
        {
            "start": "2024-01-02T06:10:00Z",
            "end": "2024-01-02T06:12:00Z",
            "category": "rem",
            "isNap": False,
        },
    ]


def test_daily_sleep_hides_intervals_when_event_sources_are_mixed() -> None:
    first = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            }
        ],
    }
    second = {
        **event("2024-01-02", is_nap=True, duration=300),
        "start_time": "2024-01-02T13:00:00Z",
        "end_time": "2024-01-02T13:05:00Z",
        "source": {"provider": "provider-demo-b", "source": "source-demo-b"},
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T13:00:00Z",
                "end_time": "2024-01-02T13:05:00Z",
                "stage": "sleeping",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [first, second], timezone_name="UTC", range_name="daily"
    )

    assert result["points"][0]["nightSleepSeconds"]["state"] == "source_ambiguous"
    assert result["intervals"] == []


def test_daily_sleep_hides_all_intervals_after_one_malformed_event() -> None:
    valid = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            }
        ],
    }
    malformed = {
        **event("2024-01-02", is_nap=True, duration=300),
        "start_time": "2024-01-02T13:00:00Z",
        "end_time": "2024-01-02T13:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "not-a-timestamp",
                "end_time": "2024-01-02T13:05:00Z",
                "stage": "sleeping",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [valid, malformed],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["points"][0]["nightSleepSeconds"]["state"] == "inconclusive"
    assert result["intervals"] == []
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_daily_sleep_hides_complete_set_when_one_night_event_has_no_intervals() -> None:
    complete = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T05:00:00Z",
        "end_time": "2024-01-02T05:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T05:00:00Z",
                "end_time": "2024-01-02T05:05:00Z",
                "stage": "light",
            }
        ],
    }
    missing_intervals = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:05:00Z",
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [complete, missing_intervals],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert result["intervals"] == []
    assert point["nightSleepSeconds"]["state"] == "inconclusive"
    assert all(metric["state"] == "inconclusive" for metric in point["stages"].values())
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


@pytest.mark.parametrize("covered_seconds", [240, 360])
def test_daily_sleep_rejects_interval_coverage_different_from_declared_sleep(
    covered_seconds: int,
) -> None:
    inconsistent = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:10:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": f"2024-01-02T06:{covered_seconds // 60:02d}:00Z",
                "stage": "sleeping",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [],
        [inconsistent],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert result["intervals"] == []
    assert point["nightSleepSeconds"]["state"] == "inconclusive"
    assert all(metric["state"] == "inconclusive" for metric in point["stages"].values())
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_daily_sleep_rejects_cross_event_interval_overlap() -> None:
    first = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            }
        ],
    }
    second = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:04:00Z",
        "end_time": "2024-01-02T06:09:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:04:00Z",
                "end_time": "2024-01-02T06:09:00Z",
                "stage": "deep",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [first, second], timezone_name="UTC", range_name="daily"
    )

    point = result["points"][0]
    assert result["intervals"] == []
    assert point["nightSleepSeconds"]["state"] == "inconclusive"
    assert all(metric["state"] == "inconclusive" for metric in point["stages"].values())
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_daily_sleep_accepts_multiple_complete_non_overlapping_events() -> None:
    night = {
        **event("2024-01-02", is_nap=False, duration=600),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:12:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            },
            {
                "start_time": "2024-01-02T06:05:00Z",
                "end_time": "2024-01-02T06:07:00Z",
                "stage": "awake",
            },
            {
                "start_time": "2024-01-02T06:07:00Z",
                "end_time": "2024-01-02T06:12:00Z",
                "stage": "deep",
            },
        ],
    }
    nap = {
        **event("2024-01-02", is_nap=True, duration=300),
        "start_time": "2024-01-02T13:00:00Z",
        "end_time": "2024-01-02T13:05:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T13:00:00Z",
                "end_time": "2024-01-02T13:05:00Z",
                "stage": "sleeping",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [night, nap], timezone_name="UTC", range_name="daily"
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"]["value"] == 600
    assert point["napsSeconds"]["value"] == 300
    assert point["stages"]["lightSeconds"]["value"] == 300
    assert point["stages"]["deepSeconds"]["value"] == 300
    assert [interval["isNap"] for interval in result["intervals"]] == [
        False,
        False,
        False,
        True,
    ]
    assert "INCONCLUSIVE" not in {warning["code"] for warning in result["warnings"]}


@pytest.mark.parametrize("invalid_kind", ["overlap", "out_of_session"])
def test_daily_sleep_hides_intervals_for_invalid_stage_sets(invalid_kind: str) -> None:
    intervals = [
        {
            "start_time": "2024-01-02T06:00:00Z",
            "end_time": "2024-01-02T06:04:00Z",
            "stage": "light",
        },
        {
            "start_time": "2024-01-02T06:03:00Z",
            "end_time": "2024-01-02T06:05:00Z",
            "stage": "deep",
        },
    ]
    if invalid_kind == "out_of_session":
        intervals[1] = {
            "start_time": "2024-01-02T06:04:00Z",
            "end_time": "2024-01-02T06:06:00Z",
            "stage": "deep",
        }
    invalid = {
        **event("2024-01-02", is_nap=False, duration=300),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:05:00Z",
        "sleep_stage_intervals": intervals,
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [invalid], timezone_name="UTC", range_name="daily"
    )

    assert result["points"][0]["nightSleepSeconds"]["state"] == "inconclusive"
    assert result["intervals"] == []


def test_summary_specific_stage_minutes_project_to_seconds_without_inference() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary(
                "2024-01-02",
                duration=420,
                sleep_duration=25_200,
                stages={
                    "awake_minutes": 0,
                    "light_minutes": 210,
                    "deep_minutes": 90,
                    "rem_minutes": None,
                },
            )
        ],
        [],
        timezone_name="UTC",
        range_name="daily",
    )

    stages = result["points"][0]["stages"]
    assert stages["awakeSeconds"] == {"state": "zero", "value": 0, "unit": "seconds"}
    assert stages["lightSeconds"] == {
        "state": "value",
        "value": 12_600,
        "unit": "seconds",
    }
    assert stages["deepSeconds"] == {
        "state": "value",
        "value": 5_400,
        "unit": "seconds",
    }
    assert stages["remSeconds"] == {"state": "null", "value": None, "unit": None}
    assert result["lightSeconds"]["totalObserved"] == 12_600
    assert result["remSeconds"]["observedDays"] == 0


def test_summary_accepts_exact_fractional_stage_minutes_from_canonical_api() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary(
                "2024-01-02",
                duration=420,
                sleep_duration=600,
                stages={
                    "awake_minutes": 0.5,
                    "light_minutes": 4.5,
                    "deep_minutes": 3,
                    "rem_minutes": 2.5,
                },
            )
        ],
        [],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"] == {
        "state": "value",
        "value": 600,
        "unit": "seconds",
    }
    assert point["stages"]["awakeSeconds"]["value"] == 30
    assert point["stages"]["lightSeconds"]["value"] == 270
    assert point["stages"]["deepSeconds"]["value"] == 180
    assert point["stages"]["remSeconds"]["value"] == 150
    assert point["unclassifiedSeconds"] == {
        "state": "zero",
        "value": 0,
        "unit": "seconds",
    }
    assert "INCONCLUSIVE" not in {warning["code"] for warning in result["warnings"]}


@pytest.mark.parametrize("range_name", ["7d", "monthly"])
def test_trend_exposes_unclassified_remainder_without_inventing_a_stage(
    range_name: str,
) -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary(
                "2024-01-02",
                duration=420,
                sleep_duration=25_200,
                stages={
                    "awake_minutes": 30,
                    "light_minutes": 180,
                    "deep_minutes": 60,
                    "rem_minutes": None,
                },
            )
        ],
        [],
        timezone_name="UTC",
        range_name=range_name,
    )

    point = next(item for item in result["points"] if item["date"] == "2024-01-02")
    assert point["unclassifiedSeconds"] == {
        "state": "value",
        "value": 10_800,
        "unit": "seconds",
    }
    assert point["stages"]["remSeconds"] == {
        "state": "null",
        "value": None,
        "unit": None,
    }
    assert result["intervals"] == []


def test_sleep_trend_keeps_canonical_aggregates_when_timeline_distribution_differs(
) -> None:
    sleep_event = {
        **event("2024-01-02", is_nap=False, duration=600),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:10:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            },
            {
                "start_time": "2024-01-02T06:05:00Z",
                "end_time": "2024-01-02T06:10:00Z",
                "stage": "deep",
            },
        ],
    }
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary(
                "2024-01-02",
                duration=600,
                sleep_duration=600,
                stages={
                    "awake_minutes": 0,
                    "light_minutes": 2,
                    "deep_minutes": 3,
                    "rem_minutes": 5,
                },
            )
        ],
        [sleep_event],
        timezone_name="UTC",
        range_name="daily",
    )

    point = result["points"][0]
    assert point["nightSleepSeconds"]["value"] == 600
    assert point["stages"]["lightSeconds"]["value"] == 120
    assert point["stages"]["deepSeconds"]["value"] == 180
    assert point["stages"]["remSeconds"]["value"] == 300
    assert result["intervals"] == [
        {
            "start": "2024-01-02T06:00:00Z",
            "end": "2024-01-02T06:05:00Z",
            "category": "light",
            "isNap": False,
        },
        {
            "start": "2024-01-02T06:05:00Z",
            "end": "2024-01-02T06:10:00Z",
            "category": "deep",
            "isNap": False,
        },
    ]
def test_trend_marks_stage_overcoverage_inconclusive() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [
            summary(
                "2024-01-02",
                duration=420,
                sleep_duration=600,
                stages={
                    "light_minutes": 8,
                    "deep_minutes": 4,
                    "rem_minutes": 0,
                },
            )
        ],
        [],
        timezone_name="UTC",
        range_name="7d",
    )

    point = result["points"][-1]
    assert point["nightSleepSeconds"]["state"] == "inconclusive"
    assert point["unclassifiedSeconds"]["state"] == "inconclusive"
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_only_generic_sleep_does_not_create_specific_stage_values() -> None:
    generic = {
        **event("2024-01-02", is_nap=False, duration=600),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:10:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:10:00Z",
                "stage": "sleeping",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [generic], timezone_name="UTC", range_name="daily"
    )

    assert all(
        metric["state"] == "unsupported"
        for metric in result["points"][0]["stages"].values()
    )


def test_mixed_overlapping_generic_and_specific_intervals_are_inconclusive() -> None:
    mixed = {
        **event("2024-01-02", is_nap=False, duration=600),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:10:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:10:00Z",
                "stage": "sleeping",
            },
            {
                "start_time": "2024-01-02T06:02:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "deep",
            },
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [mixed], timezone_name="UTC", range_name="daily"
    )

    assert result["points"][0]["stages"]["deepSeconds"]["state"] == "inconclusive"
    assert result["intervals"] == []
    assert "INCONCLUSIVE" in {warning["code"] for warning in result["warnings"]}


def test_nap_stages_keep_nap_classification_and_stay_out_of_night_totals() -> None:
    nap = {
        **event("2024-01-02", is_nap=True, duration=600),
        "start_time": "2024-01-02T13:00:00Z",
        "end_time": "2024-01-02T13:10:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T13:00:00Z",
                "end_time": "2024-01-02T13:10:00Z",
                "stage": "light",
            }
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [nap], timezone_name="UTC", range_name="daily"
    )

    assert result["intervals"][0]["isNap"] is True
    assert result["points"][0]["stages"]["lightSeconds"]["state"] == "unsupported"


def test_long_range_month_bucket_aggregates_observed_specific_stages() -> None:
    result = aggregate_sleep_trend(
        date(2024, 12, 31),
        [
            summary(
                "2024-12-30",
                duration=420,
                sleep_duration=25_200,
                stages={
                    "awake_minutes": 0,
                    "light_minutes": 210,
                    "deep_minutes": 90,
                    "rem_minutes": 120,
                },
            ),
            summary(
                "2024-12-31",
                duration=400,
                sleep_duration=24_000,
                stages={
                    "awake_minutes": 10,
                    "light_minutes": 200,
                    "deep_minutes": 80,
                    "rem_minutes": 110,
                },
            ),
        ],
        [],
        timezone_name="UTC",
        range_name="annual",
    )

    december = next(
        point for point in result["points"] if point["date"] == "2024-12-01"
    )
    assert december["stages"]["lightSeconds"]["value"] == 24_600
    assert result["lightSeconds"]["totalObserved"] == 24_600
    assert result["lightSeconds"]["averageObserved"] == 12_300


def test_same_source_name_from_different_providers_is_source_ambiguous() -> None:
    first = summary("2024-01-02", duration=420, sleep_duration=25_200)
    second_event = {
        **event("2024-01-02", is_nap=True, duration=600),
        "source": {"provider": "provider-demo-b", "source": "source-demo-a"},
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2),
        [first],
        [second_event],
        timezone_name="UTC",
        range_name="daily",
    )

    assert result["points"][0]["nightSleepSeconds"]["state"] == "source_ambiguous"


def test_mixed_sources_keep_attributed_days_but_null_all_range_aggregates() -> None:
    first = summary(
        "2024-01-01",
        duration=420,
        sleep_duration=25_200,
        stages={
            "awake_minutes": 30,
            "light_minutes": 210,
            "deep_minutes": 90,
            "rem_minutes": 120,
        },
    )
    second = {
        **summary(
            "2024-01-02",
            duration=400,
            sleep_duration=24_000,
            stages={
                "awake_minutes": 20,
                "light_minutes": 200,
                "deep_minutes": 80,
                "rem_minutes": 120,
            },
        ),
        "source": {"provider": "provider-demo-b", "source": "source-demo-b"},
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [first, second], [], timezone_name="UTC", range_name="7d"
    )

    points = {point["date"]: point for point in result["points"]}
    assert points["2024-01-01"]["nightSleepSeconds"]["value"] == 25_200
    assert points["2024-01-02"]["stages"]["deepSeconds"]["value"] == 4_800
    for name in (
        "nightSleepSeconds",
        "napsSeconds",
        "awakeSeconds",
        "lightSeconds",
        "deepSeconds",
        "remSeconds",
    ):
        assert result[name]["state"] == "source_ambiguous"
        assert result[name]["totalObserved"] is None
        assert result[name]["averageObserved"] is None
    assert "SOURCE_AMBIGUOUS" in {warning["code"] for warning in result["warnings"]}

    serialized = serialize_sleep_trend(
        {
            "schemaVersion": "1",
            "asOf": "2024-01-02T12:30:00Z",
            "timezone": "UTC",
            "data": {
                key: value
                for key, value in result.items()
                if key not in {"coverage", "warnings"}
            },
            "coverage": result["coverage"],
            "warnings": result["warnings"],
            "extensions": {},
        },
        logical_date="2024-01-02",
        timezone_name="UTC",
        from_utc="2023-12-27T00:00:00Z",
        to_utc="2024-01-03T00:00:00Z",
    )
    assert serialized["data"]["nightSleepSeconds"]["state"] == "source_ambiguous"
    assert serialized["data"]["nightSleepSeconds"]["totalObserved"] is None
    fixture = json.loads(
        (
            Path(__file__).parents[4]
            / "docs/fixtures/sleep-trend-source-ambiguous-v1.json"
        ).read_text()
    )
    assert serialized["data"] == fixture["data"]


def test_unknown_interval_stays_out_of_sleep_and_specific_stages() -> None:
    unknown_gap = {
        **event("2024-01-02", is_nap=False, duration=900),
        "start_time": "2024-01-02T06:00:00Z",
        "end_time": "2024-01-02T06:15:00Z",
        "sleep_duration_seconds": 600,
        "sleep_stage_intervals": [
            {
                "start_time": "2024-01-02T06:00:00Z",
                "end_time": "2024-01-02T06:05:00Z",
                "stage": "light",
            },
            {
                "start_time": "2024-01-02T06:05:00Z",
                "end_time": "2024-01-02T06:10:00Z",
                "stage": "unknown",
            },
            {
                "start_time": "2024-01-02T06:10:00Z",
                "end_time": "2024-01-02T06:15:00Z",
                "stage": "deep",
            },
        ],
    }

    result = aggregate_sleep_trend(
        date(2024, 1, 2), [], [unknown_gap], timezone_name="UTC", range_name="daily"
    )

    assert [interval["category"] for interval in result["intervals"]] == [
        "light",
        "unknown",
        "deep",
    ]
    point = result["points"][0]
    assert point["nightSleepSeconds"]["value"] == 600
    assert point["stages"]["lightSeconds"]["value"] == 300
    assert point["stages"]["deepSeconds"]["value"] == 300
    assert point["stages"]["remSeconds"]["state"] == "unsupported"


def test_sleep_averages_are_circular_and_timezone_local() -> None:
    result = aggregate_sleep_trend(
        date(2024, 1, 3),
        [
            {
                **summary("2024-01-02", duration=420, sleep_duration=25_200),
                "start_time": "2024-01-01T23:30:00Z",
                "end_time": "2024-01-02T07:30:00Z",
            },
            {
                **summary("2024-01-03", duration=420, sleep_duration=25_200),
                "start_time": "2024-01-02T00:30:00Z",
                "end_time": "2024-01-02T08:30:00Z",
            },
        ],
        [],
        timezone_name="UTC",
        range_name="7d",
    )

    assert result["averageBedtime"].endswith("T00:00:00Z")
    assert result["averageWakeTime"].endswith("T08:00:00Z")


def test_dst_boundary_uses_local_end_date_without_changing_interval_seconds() -> None:
    dst_event = {
        **event("2024-03-10", is_nap=False, duration=3_600),
        "start_time": "2024-03-10T06:30:00Z",
        "end_time": "2024-03-10T07:30:00Z",
        "sleep_stage_intervals": [
            {
                "start_time": "2024-03-10T06:30:00Z",
                "end_time": "2024-03-10T07:30:00Z",
                "stage": "rem",
            }
        ],
    }
    dst_event.pop("date")

    result = aggregate_sleep_trend(
        date(2024, 3, 10),
        [],
        [dst_event],
        timezone_name="America/New_York",
        range_name="daily",
    )

    assert result["points"][0]["nightSleepSeconds"]["value"] == 3_600
    assert result["points"][0]["stages"]["remSeconds"]["value"] == 3_600
    assert result["intervals"][0]["start"] == "2024-03-10T06:30:00Z"
    assert result["intervals"][0]["end"] == "2024-03-10T07:30:00Z"
