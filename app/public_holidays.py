"""Australian public holidays for cost and Gantt scheduling.

National days plus state / territory extras. Grand Final Friday (VIC) and
WA King's Birthday use announced dates where known; unknown years omit the
variable day so planners can skip it as an RDO.
"""

from __future__ import annotations

from datetime import date, timedelta

JURISDICTIONS = ("VIC", "NSW", "QLD", "SA", "WA", "TAS", "ACT", "NT")

JURISDICTION_LABELS = {
    "VIC": "Victoria",
    "NSW": "New South Wales",
    "QLD": "Queensland",
    "SA": "South Australia",
    "WA": "Western Australia",
    "TAS": "Tasmania",
    "ACT": "Australian Capital Territory",
    "NT": "Northern Territory",
}

# AFL Grand Final Friday (day before GF) — extend as years are announced
_AFL_GF_FRIDAY: dict[int, date] = {
    2024: date(2024, 9, 27),
    2025: date(2025, 9, 26),
    2026: date(2026, 9, 25),
    2027: date(2027, 9, 24),
}

# WA King's Birthday is gazetted (often last Monday of September).
_WA_KINGS_BIRTHDAY: dict[int, date] = {
    2024: date(2024, 9, 23),
    2025: date(2025, 9, 29),
    2026: date(2026, 9, 28),
    2027: date(2027, 9, 27),
}


def normalize_jurisdiction(raw) -> str:
    code = str(raw or "VIC").strip().upper()
    return code if code in JURISDICTIONS else "VIC"


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
    """If holiday falls on weekend, observe on following Monday (common rule)."""
    if d.weekday() == 5:  # Sat → Mon
        return d + timedelta(days=2)
    if d.weekday() == 6:  # Sun → Mon
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday in month (weekday: 0=Mon … 6=Sun)."""
    d = date(year, month, 1)
    delta = (weekday - d.weekday()) % 7
    d = d + timedelta(days=delta)
    d = d + timedelta(weeks=n - 1)
    return d


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    delta = (d.weekday() - weekday) % 7
    return d - timedelta(days=delta)


def _monday_on_or_after(year: int, month: int, day: int) -> date:
    d = date(year, month, day)
    return d + timedelta(days=(0 - d.weekday()) % 7)


def _collect(year: int, extras: list[tuple[date, str, bool]]) -> dict[date, str]:
    out: dict[date, str] = {}

    def add(d: date, name: str, *, observe: bool = False) -> None:
        key = _observed_weekday(d) if observe else d
        label = name if key == d else f"{name} (observed)"
        out[key] = label
        if key != d:
            out.setdefault(d, name)

    add(date(year, 1, 1), "New Year's Day", observe=True)
    add(date(year, 1, 26), "Australia Day", observe=True)
    easter = easter_sunday(year)
    add(easter - timedelta(days=2), "Good Friday")
    add(easter - timedelta(days=1), "Easter Saturday")
    add(easter, "Easter Sunday")
    add(easter + timedelta(days=1), "Easter Monday")
    add(date(year, 4, 25), "ANZAC Day")
    add(date(year, 12, 25), "Christmas Day", observe=True)
    add(date(year, 12, 26), "Boxing Day", observe=True)
    for d, name, observe in extras:
        add(d, name, observe=observe)
    return out


def holidays_for_year(year: int, jurisdiction: str = "VIC") -> dict[date, str]:
    """Return {date: name} for ``jurisdiction`` public holidays in ``year``."""
    code = normalize_jurisdiction(jurisdiction)
    extras: list[tuple[date, str, bool]] = []
    if code == "VIC":
        extras = [
            (_nth_weekday(year, 3, 0, 2), "Labour Day", False),
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 11, 1, 1), "Melbourne Cup", False),
        ]
        gf = _AFL_GF_FRIDAY.get(year)
        if gf:
            extras.append((gf, "Friday before AFL Grand Final", False))
    elif code == "NSW":
        extras = [
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 10, 0, 1), "Labour Day", False),
        ]
    elif code == "QLD":
        extras = [
            (_nth_weekday(year, 5, 0, 1), "Labour Day", False),
            (_nth_weekday(year, 10, 0, 1), "King's Birthday", False),
        ]
    elif code == "SA":
        extras = [
            (_nth_weekday(year, 3, 0, 2), "Adelaide Cup", False),
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 10, 0, 1), "Labour Day", False),
        ]
    elif code == "WA":
        extras = [
            (_nth_weekday(year, 3, 0, 1), "Labour Day", False),
            (_nth_weekday(year, 6, 0, 1), "Western Australia Day", False),
        ]
        kb = _WA_KINGS_BIRTHDAY.get(year) or _last_weekday(year, 9, 0)
        extras.append((kb, "King's Birthday", False))
    elif code == "TAS":
        extras = [
            (_nth_weekday(year, 3, 0, 2), "Eight Hours Day", False),
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 11, 0, 1), "Recreation Day", False),
        ]
    elif code == "ACT":
        extras = [
            (_nth_weekday(year, 3, 0, 2), "Canberra Day", False),
            (_monday_on_or_after(year, 5, 27), "Reconciliation Day", False),
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 10, 0, 1), "Labour Day", False),
        ]
    elif code == "NT":
        extras = [
            (_nth_weekday(year, 5, 0, 1), "May Day", False),
            (_nth_weekday(year, 6, 0, 2), "King's Birthday", False),
            (_nth_weekday(year, 8, 0, 1), "Picnic Day", False),
        ]
    return _collect(year, extras)


def victorian_holidays(year: int) -> dict[date, str]:
    return holidays_for_year(year, "VIC")


def holidays_between(start: date, end: date, jurisdiction: str = "VIC") -> dict[date, str]:
    if end < start:
        start, end = end, start
    out: dict[date, str] = {}
    code = normalize_jurisdiction(jurisdiction)
    for year in range(start.year, end.year + 1):
        for d, name in holidays_for_year(year, code).items():
            if start <= d <= end:
                out[d] = name
    return out


def is_public_holiday(d: date, jurisdiction: str = "VIC") -> bool:
    return d in holidays_for_year(d.year, jurisdiction)
