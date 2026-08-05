"""Victorian public holidays for cost scheduling.

Computes fixed / observed / Easter-based holidays. Grand Final Friday is
year-specific (AFL) — known values are listed; unknown years omit it so
planners can skip manually as an RDO.
"""

from __future__ import annotations

from datetime import date, timedelta

# AFL Grand Final Friday (day before GF) — extend as years are announced
_AFL_GF_FRIDAY: dict[int, date] = {
    2024: date(2024, 9, 27),
    2025: date(2025, 9, 26),
    2026: date(2026, 9, 25),
    2027: date(2027, 9, 24),
}


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_weekday(d: date) -> date:
    """If holiday falls on weekend, observe on following Monday (common VIC rule)."""
    if d.weekday() == 5:  # Sat → Mon
        return d + timedelta(days=2)
    if d.weekday() == 6:  # Sun → Mon
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday in month (weekday: 0=Mon … 6=Sun)."""
    d = date(year, month, 1)
    # advance to first desired weekday
    delta = (weekday - d.weekday()) % 7
    d = d + timedelta(days=delta)
    d = d + timedelta(weeks=n - 1)
    return d


def victorian_holidays(year: int) -> dict[date, str]:
    """Return {date: name} for Victorian public holidays in ``year``."""
    out: dict[date, str] = {}

    def add(d: date, name: str, *, observe: bool = False) -> None:
        key = _observed_weekday(d) if observe else d
        # Keep original name; if observation moved, note it
        label = name if key == d else f"{name} (observed)"
        out[key] = label
        # Also mark the actual weekend date when observed elsewhere so schedulers
        # recognise both (some jobs still treat the calendar day as PH).
        if key != d:
            out.setdefault(d, name)

    add(date(year, 1, 1), "New Year's Day", observe=True)
    add(date(year, 1, 26), "Australia Day", observe=True)
    add(_nth_weekday(year, 3, 0, 2), "Labour Day")  # 2nd Monday March

    easter = easter_sunday(year)
    add(easter - timedelta(days=2), "Good Friday")
    add(easter - timedelta(days=1), "Easter Saturday")
    add(easter, "Easter Sunday")
    add(easter + timedelta(days=1), "Easter Monday")

    add(date(year, 4, 25), "ANZAC Day")  # VIC: still PH if weekend
    add(_nth_weekday(year, 6, 0, 2), "King's Birthday")  # 2nd Monday June

    gf = _AFL_GF_FRIDAY.get(year)
    if gf:
        add(gf, "Friday before AFL Grand Final")

    add(_nth_weekday(year, 11, 1, 1), "Melbourne Cup")  # 1st Tuesday November
    add(date(year, 12, 25), "Christmas Day", observe=True)
    add(date(year, 12, 26), "Boxing Day", observe=True)

    return out


def holidays_between(start: date, end: date) -> dict[date, str]:
    if end < start:
        start, end = end, start
    out: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for d, name in victorian_holidays(year).items():
            if start <= d <= end:
                out[d] = name
    return out


def is_public_holiday(d: date) -> bool:
    return d in victorian_holidays(d.year)
