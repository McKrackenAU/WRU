"""Australian weekday business-day helpers (weekends skipped; public holidays not loaded)."""

from __future__ import annotations

from datetime import date, timedelta


def is_business_day(d: date) -> bool:
    return d.weekday() < 5  # Mon–Fri


def add_business_days(start: date, days: int) -> date:
    """Add (or subtract) N business days from start. `days=0` returns start (or next bus day)."""
    if days == 0:
        cursor = start
        while not is_business_day(cursor):
            cursor += timedelta(days=1)
        return cursor
    step = 1 if days > 0 else -1
    remaining = abs(days)
    cursor = start
    while remaining:
        cursor += timedelta(days=step)
        if is_business_day(cursor):
            remaining -= 1
    return cursor


def business_days_between(start: date, end: date) -> int:
    """Count business days from start to end inclusive of end if end is a business day,
    exclusive of start (elapsed wait). If end < start, returns negative.
    """
    if start == end:
        return 0
    sign = 1 if end > start else -1
    cursor = start
    target = end
    count = 0
    while cursor != target:
        cursor += timedelta(days=sign)
        if is_business_day(cursor):
            count += sign
    return count


def business_days_elapsed(start: date | None, today: date | None = None) -> int | None:
    if start is None:
        return None
    today = today or date.today()
    if today < start:
        return 0
    return max(0, business_days_between(start, today))
