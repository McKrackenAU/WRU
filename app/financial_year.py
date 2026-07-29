from __future__ import annotations

from datetime import date


def australian_financial_year(d: date | None = None) -> str:
    """Return FY label like '2025-26' (1 Jul – 30 Jun)."""
    d = d or date.today()
    if d.month >= 7:
        start = d.year
    else:
        start = d.year - 1
    end = (start + 1) % 100
    return f"{start}-{end:02d}"


def fy_start_date(fy: str) -> date:
    start_year = int(fy.split("-")[0])
    return date(start_year, 7, 1)


def fy_end_date(fy: str) -> date:
    start_year = int(fy.split("-")[0])
    return date(start_year + 1, 6, 30)


def fy_choices(around: date | None = None, back: int = 6, forward: int = 1) -> list[str]:
    around = around or date.today()
    current = australian_financial_year(around)
    start_year = int(current.split("-")[0])
    years = []
    for y in range(start_year - back, start_year + forward + 1):
        years.append(f"{y}-{(y + 1) % 100:02d}")
    return list(reversed(years))
