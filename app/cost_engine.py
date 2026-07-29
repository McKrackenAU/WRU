"""Traffic management cost calculations: shifts, VMS, and 24h closure compare."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Literal

ShiftType = Literal["day", "night"]


def money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def split_ordinary_ot(shift_hours: float, overtime_after: float) -> tuple[float, float]:
    ordinary = min(shift_hours, overtime_after)
    ot = max(0.0, shift_hours - overtime_after)
    return ordinary, ot


def labour_cost_for_shift(
    *,
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
    crew: list[dict[str, Any]],
    rates_by_id: dict[int, Any],
) -> dict[str, Any]:
    """crew items: {rate_id, quantity}."""
    ordinary_h, ot_h = split_ordinary_ot(shift_hours, overtime_after)
    lines = []
    total = 0.0
    for item in crew:
        rate_id = int(item["rate_id"])
        qty = float(item.get("quantity") or 0)
        if qty <= 0:
            continue
        rate = rates_by_id.get(rate_id)
        if not rate:
            continue
        if shift_type == "night":
            ord_rate = float(rate.night_ordinary)
            ot_rate = float(rate.night_overtime)
        else:
            ord_rate = float(rate.day_ordinary)
            ot_rate = float(rate.day_overtime)
        line_total = qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": rate_id,
                "name": rate.name,
                "quantity": qty,
                "shift_type": shift_type,
                "ordinary_hours": ordinary_h,
                "overtime_hours": ot_h,
                "ordinary_rate": money(ord_rate),
                "overtime_rate": money(ot_rate),
                "line_total": money(line_total),
            }
        )
    return {"lines": lines, "shift_labour_total": money(total)}


def vms_calendar_days(
    *,
    lead_days: int,
    works_start: date,
    works_end: date,
) -> dict[str, Any]:
    """VMS out `lead_days` before works start, through works end date (inclusive).

    Day rate is charged once per calendar day the board is deployed — never
    multiplied by how many traffic shifts fall on that day.
    """
    if works_end < works_start:
        raise ValueError("works_end must be on or after works_start")
    deploy_start = works_start - timedelta(days=max(0, lead_days))
    deploy_end = works_end
    days = (deploy_end - deploy_start).days + 1
    return {
        "deploy_start": deploy_start.isoformat(),
        "deploy_end": deploy_end.isoformat(),
        "lead_days": lead_days,
        "works_days": (works_end - works_start).days + 1,
        "billable_days": days,
    }


def vms_cost(
    *,
    quantity: int,
    lead_days: int,
    works_start: date,
    works_end: date,
    delivery_rate: float,
    collection_rate: float,
    day_rate: float,
) -> dict[str, Any]:
    qty = max(0, int(quantity))
    span = vms_calendar_days(
        lead_days=lead_days, works_start=works_start, works_end=works_end
    )
    billable = span["billable_days"]
    delivery = qty * delivery_rate
    collection = qty * collection_rate
    hire = qty * day_rate * billable
    return {
        **span,
        "quantity": qty,
        "delivery_rate": money(delivery_rate),
        "collection_rate": money(collection_rate),
        "day_rate": money(day_rate),
        "delivery_total": money(delivery),
        "collection_total": money(collection),
        "hire_total": money(hire),
        "vms_total": money(delivery + collection + hire),
        "note": "VMS hire uses calendar day rate × boards × days on site (lead + works). Not per shift.",
    }


def calculate_standard(payload: dict[str, Any], settings: Any, rates: list[Any]) -> dict[str, Any]:
    overtime_after = float(
        payload.get("overtime_after_hours", settings.overtime_after_hours)
    )
    shift_hours = float(payload["shift_hours"])
    shift_type: ShiftType = payload.get("shift_type") or "day"
    if shift_type not in ("day", "night"):
        raise ValueError("shift_type must be 'day' or 'night'")
    total_shifts = int(payload["total_shifts"])
    if shift_hours <= 0 or total_shifts <= 0:
        raise ValueError("shift_hours and total_shifts must be positive")

    works_start = date.fromisoformat(payload["works_start"])
    works_end = date.fromisoformat(payload.get("works_end") or payload["works_start"])
    lead_days = int(payload.get("vms_lead_days", settings.vms_lead_days_default))
    vms_qty = int(payload.get("vms_quantity") or 0)

    rates_by_id = {r.id: r for r in rates}
    labour = labour_cost_for_shift(
        shift_hours=shift_hours,
        shift_type=shift_type,
        overtime_after=overtime_after,
        crew=payload.get("crew") or [],
        rates_by_id=rates_by_id,
    )
    site_labour = labour["shift_labour_total"] * total_shifts
    vms = vms_cost(
        quantity=vms_qty,
        lead_days=lead_days,
        works_start=works_start,
        works_end=works_end,
        delivery_rate=float(
            payload.get("vms_delivery_rate", settings.vms_delivery_rate)
        ),
        collection_rate=float(
            payload.get("vms_collection_rate", settings.vms_collection_rate)
        ),
        day_rate=float(payload.get("vms_day_rate", settings.vms_day_rate)),
    )

    grand = site_labour + vms["vms_total"]
    return {
        "mode": "standard",
        "inputs_echo": {
            "shift_hours": shift_hours,
            "shift_type": shift_type,
            "total_shifts": total_shifts,
            "overtime_after_hours": overtime_after,
            "works_start": works_start.isoformat(),
            "works_end": works_end.isoformat(),
        },
        "per_shift": labour,
        "site_labour_total": money(site_labour),
        "vms": vms,
        "site_traffic_total": money(grand),
    }


def _shift_type_sequence(start: datetime, shift_hours: float, count: int) -> list[ShiftType]:
    """Classify each back-to-back shift as day (06:00–18:00) or night."""
    types: list[ShiftType] = []
    cursor = start
    for _ in range(count):
        # Use midpoint of shift to classify
        mid = cursor + timedelta(hours=shift_hours / 2)
        hour = mid.hour + mid.minute / 60
        types.append("day" if 6 <= hour < 18 else "night")
        cursor += timedelta(hours=shift_hours)
    return types


def _closure_option(
    *,
    label: str,
    shift_hours: float,
    start: datetime,
    end: datetime,
    overtime_after: float,
    crew: list[dict[str, Any]],
    rates_by_id: dict[int, Any],
) -> dict[str, Any]:
    duration_h = (end - start).total_seconds() / 3600
    if duration_h <= 0:
        raise ValueError("closure end must be after start")
    shifts = int(math.ceil(duration_h / shift_hours - 1e-9))
    types = _shift_type_sequence(start, shift_hours, shifts)

    # Aggregate labour: group identical shift types for efficiency, but also
    # produce a per-shift breakdown for transparency.
    per_shift = []
    labour_total = 0.0
    day_shifts = 0
    night_shifts = 0
    for idx, stype in enumerate(types):
        detail = labour_cost_for_shift(
            shift_hours=shift_hours,
            shift_type=stype,
            overtime_after=overtime_after,
            crew=crew,
            rates_by_id=rates_by_id,
        )
        labour_total += detail["shift_labour_total"]
        if stype == "day":
            day_shifts += 1
        else:
            night_shifts += 1
        per_shift.append(
            {
                "index": idx + 1,
                "shift_type": stype,
                "hours": shift_hours,
                "labour_total": detail["shift_labour_total"],
                "lines": detail["lines"],
            }
        )

    return {
        "label": label,
        "shift_hours": shift_hours,
        "shifts_required": shifts,
        "day_shifts": day_shifts,
        "night_shifts": night_shifts,
        "duration_hours": money(duration_h),
        "labour_total": money(labour_total),
        "per_shift": per_shift,
    }


def calculate_closure_24h(payload: dict[str, Any], settings: Any, rates: list[Any]) -> dict[str, Any]:
    """Compare 3×8h vs 2×12h patterns across a continuous closure window."""
    start = datetime.fromisoformat(payload["closure_start"])
    end = datetime.fromisoformat(payload["closure_end"])
    if end <= start:
        raise ValueError("closure_end must be after closure_start")

    overtime_after = float(
        payload.get("overtime_after_hours", settings.overtime_after_hours)
    )
    lead_days = int(payload.get("vms_lead_days", settings.vms_lead_days_default))
    vms_qty = int(payload.get("vms_quantity") or 0)
    crew = payload.get("crew") or []
    rates_by_id = {r.id: r for r in rates}

    opt_3x8 = _closure_option(
        label="3 × 8-hour shifts (per 24h coverage)",
        shift_hours=8,
        start=start,
        end=end,
        overtime_after=overtime_after,
        crew=crew,
        rates_by_id=rates_by_id,
    )
    opt_2x12 = _closure_option(
        label="2 × 12-hour shifts (per 24h coverage)",
        shift_hours=12,
        start=start,
        end=end,
        overtime_after=overtime_after,
        crew=crew,
        rates_by_id=rates_by_id,
    )

    # VMS: calendar days only (not × number of shifts in a day)
    vms = vms_cost(
        quantity=vms_qty,
        lead_days=lead_days,
        works_start=start.date(),
        works_end=end.date(),
        delivery_rate=float(
            payload.get("vms_delivery_rate", settings.vms_delivery_rate)
        ),
        collection_rate=float(
            payload.get("vms_collection_rate", settings.vms_collection_rate)
        ),
        day_rate=float(payload.get("vms_day_rate", settings.vms_day_rate)),
    )

    for opt in (opt_3x8, opt_2x12):
        opt["vms_total"] = vms["vms_total"]
        opt["grand_total"] = money(opt["labour_total"] + vms["vms_total"])

    cheaper = (
        "3x8"
        if opt_3x8["grand_total"] < opt_2x12["grand_total"]
        else "2x12"
        if opt_2x12["grand_total"] < opt_3x8["grand_total"]
        else "equal"
    )
    saving = money(abs(opt_3x8["grand_total"] - opt_2x12["grand_total"]))

    return {
        "mode": "closure_24h",
        "inputs_echo": {
            "closure_start": start.isoformat(sep=" "),
            "closure_end": end.isoformat(sep=" "),
            "overtime_after_hours": overtime_after,
            "duration_hours": money((end - start).total_seconds() / 3600),
        },
        "vms": vms,
        "option_3x8": opt_3x8,
        "option_2x12": opt_2x12,
        "recommendation": {
            "cheaper": cheaper,
            "saving": saving,
            "summary": (
                f"3×8 total ${opt_3x8['grand_total']:,.2f} vs 2×12 total "
                f"${opt_2x12['grand_total']:,.2f}. "
                + (
                    "Equal cost."
                    if cheaper == "equal"
                    else f"{'3×8' if cheaper == '3x8' else '2×12'} is cheaper by ${saving:,.2f}."
                )
                + " VMS charged by calendar day (not per shift)."
            ),
        },
    }
