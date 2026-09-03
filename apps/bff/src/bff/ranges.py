from __future__ import annotations

from datetime import date, timedelta

TREND_RANGES = frozenset({"daily", "7d", "monthly", "180d", "annual"})


def trend_date_scope(
    logical_date: date, range_name: str
) -> tuple[date, date, list[str]]:
    if range_name == "daily":
        start_date = end_date = logical_date
        labels = [logical_date.isoformat()]
    elif range_name == "7d":
        start_date, end_date = logical_date - timedelta(days=6), logical_date
        labels = [(start_date + timedelta(days=i)).isoformat() for i in range(7)]
    elif range_name == "monthly":
        start_date = logical_date.replace(day=1)
        end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(
            day=1
        ) - timedelta(days=1)
        labels = [
            (start_date + timedelta(days=i)).isoformat()
            for i in range((end_date - start_date).days + 1)
        ]
    elif range_name == "180d":
        start_date, end_date = logical_date - timedelta(days=179), logical_date
        labels = []
        bucket = start_date.replace(day=1)
        last_bucket = end_date.replace(day=1)
        while bucket <= last_bucket:
            labels.append(bucket.isoformat())
            bucket = (bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif range_name == "annual":
        start_date = logical_date.replace(month=1, day=1)
        end_date = logical_date.replace(month=12, day=31)
        labels = [start_date.replace(month=i).isoformat() for i in range(1, 13)]
    else:
        raise ValueError(f"unsupported trend range: {range_name}")
    return start_date, end_date, labels
