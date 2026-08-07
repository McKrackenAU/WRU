"""Reactive Gantt date computation using the shared work calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .cost_engine import build_work_schedule


def _parse_dates(values: list | None) -> set[date]:
    out: set[date] = set()
    for raw in values or []:
        if not raw:
            continue
        if isinstance(raw, date) and not isinstance(raw, datetime):
            out.add(raw)
            continue
        try:
            out.add(date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    return out


def next_work_day_after(
    last_end: date,
    *,
    work_weekdays: list[int],
    skip_public_holidays: bool,
    skip_sunday_before_monday_ph: bool,
    rdo_dates: set[date],
    include_dates: set[date],
    exclude_dates: set[date],
) -> date:
    """First schedulable work day strictly after ``last_end``."""
    probe = last_end + timedelta(days=1)
    # Schedule a single day starting at probe — may skip ahead for PH/RDO
    scheduled = build_work_schedule(
        probe,
        1,
        work_weekdays=work_weekdays,
        skip_public_holidays=skip_public_holidays,
        skip_sunday_before_monday_ph=skip_sunday_before_monday_ph,
        rdo_dates=rdo_dates,
        include_dates=include_dates,
        exclude_dates=exclude_dates,
    )
    return date.fromisoformat(scheduled[0]["date"])


def compute_item_window(
    start: date,
    shifts_count: int,
    *,
    work_weekdays: list[int],
    skip_public_holidays: bool,
    skip_sunday_before_monday_ph: bool,
    rdo_dates: set[date],
    include_dates: set[date],
    exclude_dates: set[date],
) -> tuple[date, date, list[dict[str, Any]]]:
    shifts = max(1, int(shifts_count))
    schedule = build_work_schedule(
        start,
        shifts,
        work_weekdays=work_weekdays,
        skip_public_holidays=skip_public_holidays,
        skip_sunday_before_monday_ph=skip_sunday_before_monday_ph,
        rdo_dates=rdo_dates,
        include_dates=include_dates,
        exclude_dates=exclude_dates,
    )
    planned_start = date.fromisoformat(schedule[0]["date"])
    planned_end = date.fromisoformat(schedule[-1]["date"])
    return planned_start, planned_end, schedule


def recompute_board_dates(
    board: Any,
    items: list[Any],
    *,
    subcontractors_by_id: dict[int, Any] | None = None,
) -> list[dict[str, Any]]:
    """Recompute planned_start/end for ordered gantt items; mutates items in place.

    Returns a list of public dicts with schedule detail for the API response.
    """
    subs = subcontractors_by_id or {}
    board_weekdays = list(board.work_weekdays or [0, 1, 2, 3, 4])
    board_rdo = _parse_dates(board.rdo_dates)
    board_exclude = _parse_dates(board.exclude_dates)
    board_include = _parse_dates(board.include_dates)

    ordered = sorted(items, key=lambda i: (i.position, i.id or 0))
    cursor_start = board.anchor_start
    previous_end: date | None = None
    out: list[dict[str, Any]] = []

    for item in ordered:
        sub = subs.get(item.subcontractor_id) if item.subcontractor_id else None
        weekdays = list((sub.work_weekdays if sub and sub.work_weekdays else None) or board_weekdays)
        skip_ph = bool(sub.skip_public_holidays) if sub is not None else bool(board.skip_public_holidays)
        skip_sun = (
            bool(sub.skip_sunday_before_monday_ph)
            if sub is not None
            else bool(board.skip_sunday_before_monday_ph)
        )
        rdo = set(board_rdo)
        rdo |= _parse_dates(getattr(sub, "rdo_dates", None) if sub else None)
        rdo |= _parse_dates(item.rdo_dates)
        exclude = set(board_exclude) | _parse_dates(item.exclude_dates)
        include = set(board_include) | _parse_dates(item.include_dates)

        link_mode = (item.link_mode or "after_previous").strip().lower()
        if link_mode == "fixed_start" and item.fixed_start:
            start = item.fixed_start
        elif previous_end is not None:
            start = next_work_day_after(
                previous_end,
                work_weekdays=weekdays,
                skip_public_holidays=skip_ph,
                skip_sunday_before_monday_ph=skip_sun,
                rdo_dates=rdo,
                include_dates=include,
                exclude_dates=exclude,
            )
        elif cursor_start:
            start = cursor_start
        elif item.fixed_start:
            start = item.fixed_start
        else:
            # No anchor yet — leave blank
            item.planned_start = None
            item.planned_end = None
            out.append(_item_public(item, schedule=[]))
            continue

        try:
            planned_start, planned_end, schedule = compute_item_window(
                start,
                item.shifts_count,
                work_weekdays=weekdays,
                skip_public_holidays=skip_ph,
                skip_sunday_before_monday_ph=skip_sun,
                rdo_dates=rdo,
                include_dates=include,
                exclude_dates=exclude,
            )
        except ValueError:
            item.planned_start = start
            item.planned_end = None
            out.append(_item_public(item, schedule=[], error="Could not schedule within calendar horizon"))
            previous_end = start
            continue

        item.planned_start = planned_start
        item.planned_end = planned_end
        previous_end = planned_end
        out.append(_item_public(item, schedule=schedule))

    return out


def _item_public(item: Any, *, schedule: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    site = getattr(item, "site", None)
    sub = getattr(item, "subcontractor", None)
    return {
        "id": item.id,
        "board_id": item.board_id,
        "site_id": item.site_id,
        "position": item.position,
        "shifts_count": item.shifts_count,
        "link_mode": item.link_mode,
        "fixed_start": item.fixed_start.isoformat() if item.fixed_start else None,
        "subcontractor_id": item.subcontractor_id,
        "subcontractor_name": sub.name if sub else None,
        "planned_start": item.planned_start.isoformat() if item.planned_start else None,
        "planned_end": item.planned_end.isoformat() if item.planned_end else None,
        "rdo_dates": list(item.rdo_dates or []),
        "exclude_dates": list(item.exclude_dates or []),
        "include_dates": list(item.include_dates or []),
        "notes": item.notes,
        "site_road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
        "site_program": site.program if site else None,
        "schedule": schedule,
        "error": error,
    }
