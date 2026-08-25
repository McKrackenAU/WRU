"""Traffic management cost calculations: TC packs, allowances, VMS, 24h compare."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Literal

from .public_holidays import holidays_between

ShiftType = Literal["day", "night"]
RateTier = Literal["weekday", "saturday", "sunday", "public_holiday"]

INF = 10**18
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def hour_of_day(value: datetime | float | int) -> float:
    if isinstance(value, datetime):
        return value.hour + value.minute / 60.0 + value.second / 3600.0
    return float(value) % 24


def classify_shift_type(
    when: datetime | float | int,
    *,
    day_start_hour: float = 6.0,
    day_end_hour: float = 18.0,
) -> ShiftType:
    """Return day if midpoint/time falls in [day_start, day_end), else night."""
    hour = hour_of_day(when)
    start = float(day_start_hour) % 24
    end = float(day_end_hour) % 24
    if start == end:
        return "day"
    if start < end:
        return "day" if start <= hour < end else "night"
    # Window wraps midnight (unusual for "day" but supported)
    return "day" if hour >= start or hour < end else "night"


def split_ordinary_ot(shift_hours: float, overtime_after: float) -> tuple[float, float]:
    ordinary = min(shift_hours, overtime_after)
    ot = max(0.0, shift_hours - overtime_after)
    return ordinary, ot


def classify_rate_tier(d: date, *, holiday_names: dict[date, str] | None = None) -> RateTier:
    holidays = holiday_names if holiday_names is not None else holidays_between(d, d)
    if d in holidays:
        return "public_holiday"
    if d.weekday() == 5:
        return "saturday"
    if d.weekday() == 6:
        return "sunday"
    return "weekday"


def rate_unit_rates(
    rate: Any,
    shift_type: ShiftType,
    rate_tier: RateTier = "weekday",
) -> tuple[float, float]:
    """Ordinary / OT unit rates for a calendar tier.

    Weekend (Sat+Sun) uses the Sunday / weekend column. PH falls back to weekend,
    then night, so existing cards keep working until those columns are filled in.
    """
    if rate_tier in ("saturday", "sunday", "weekend"):
        # Weekend is a single card: Sunday is the source of truth, Saturday copies it.
        o = float(getattr(rate, "sunday_ordinary", 0) or 0) or float(getattr(rate, "saturday_ordinary", 0) or 0)
        t = float(getattr(rate, "sunday_overtime", 0) or 0) or float(getattr(rate, "saturday_overtime", 0) or 0)
        if o > 0 or t > 0:
            return (o if o > 0 else t), (t if t > 0 else o)
        return float(rate.night_ordinary), float(rate.night_overtime)

    if rate_tier == "public_holiday":
        o = float(getattr(rate, "public_holiday_ordinary", 0) or 0)
        t = float(getattr(rate, "public_holiday_overtime", 0) or 0)
        if o <= 0 and t <= 0:
            o = float(getattr(rate, "sunday_ordinary", 0) or 0) or float(getattr(rate, "saturday_ordinary", 0) or 0)
            t = float(getattr(rate, "sunday_overtime", 0) or 0) or float(getattr(rate, "saturday_overtime", 0) or 0)
        if o > 0 or t > 0:
            return (o if o > 0 else t), (t if t > 0 else o)
        return float(rate.night_overtime), float(rate.night_overtime)

    if shift_type == "night":
        return float(rate.night_ordinary), float(rate.night_overtime)
    return float(rate.day_ordinary), float(rate.day_overtime)


def unit_shift_cost(
    rate: Any,
    *,
    shift_type: ShiftType,
    ordinary_h: float,
    ot_h: float,
    rate_tier: RateTier = "weekday",
) -> float:
    ord_rate, ot_rate = rate_unit_rates(rate, shift_type, rate_tier)
    return ordinary_h * ord_rate + ot_h * ot_rate


def parse_date_list(raw: Any) -> set[date]:
    out: set[date] = set()
    if not raw:
        return out
    for item in raw:
        try:
            out.add(date.fromisoformat(str(item)[:10]))
        except ValueError:
            continue
    return out


def build_work_schedule(
    works_start: date,
    days_of_work: int,
    *,
    work_weekdays: list[int] | None = None,
    skip_public_holidays: bool = True,
    skip_sunday_before_monday_ph: bool = True,
    rdo_dates: set[date] | None = None,
    include_dates: set[date] | None = None,
    exclude_dates: set[date] | None = None,
    max_span_days: int = 400,
) -> list[dict[str, Any]]:
    """Expand a start date + target work-day count into concrete work dates.

    ``work_weekdays`` uses Python weekday numbers (0=Mon … 6=Sun).
    """
    if days_of_work <= 0:
        raise ValueError("days_of_work must be positive")
    weekdays = set(work_weekdays if work_weekdays is not None else [0, 1, 2, 3, 4])
    if not weekdays:
        raise ValueError("Select at least one day of the week")
    rdo = rdo_dates or set()
    include = include_dates or set()
    exclude = exclude_dates or set()

    horizon_end = works_start + timedelta(days=max_span_days)
    holiday_names = holidays_between(works_start - timedelta(days=2), horizon_end + timedelta(days=2))

    selected: list[dict[str, Any]] = []
    cursor = works_start
    guard = 0
    while len(selected) < days_of_work and guard <= max_span_days:
        guard += 1
        d = cursor
        cursor += timedelta(days=1)
        flags: list[str] = []
        ph_name = holiday_names.get(d)
        if ph_name:
            flags.append("public_holiday")
        if d.weekday() == 5:
            flags.append("saturday")
        if d.weekday() == 6:
            flags.append("sunday")
        if d in rdo:
            flags.append("rdo")

        forced_in = d in include
        forced_out = d in exclude or d in rdo

        if forced_out and not forced_in:
            continue
        if not forced_in:
            if d.weekday() not in weekdays:
                continue
            if skip_public_holidays and ph_name:
                continue
            if (
                skip_sunday_before_monday_ph
                and d.weekday() == 6
                and (d + timedelta(days=1)) in holiday_names
            ):
                flags.append("skip_before_monday_ph")
                continue

        tier = classify_rate_tier(d, holiday_names=holiday_names)
        selected.append(
            {
                "date": d.isoformat(),
                "weekday": d.weekday(),
                "weekday_label": WEEKDAY_NAMES[d.weekday()],
                "rate_tier": tier,
                "flags": flags,
                "holiday_name": ph_name,
                "included": True,
            }
        )

    if len(selected) < days_of_work:
        raise ValueError(
            f"Could only schedule {len(selected)} of {days_of_work} work days "
            f"within {max_span_days} calendar days — widen the weekday pattern or reduce days of work."
        )
    return selected


def preview_schedule_window(
    works_start: date,
    *,
    days_of_work: int,
    work_weekdays: list[int] | None = None,
    skip_public_holidays: bool = True,
    skip_sunday_before_monday_ph: bool = True,
    rdo_dates: set[date] | None = None,
    include_dates: set[date] | None = None,
    exclude_dates: set[date] | None = None,
    pad_days: int = 14,
) -> list[dict[str, Any]]:
    """Calendar preview covering the scheduled span (+pad) with include flags."""
    work = build_work_schedule(
        works_start,
        days_of_work,
        work_weekdays=work_weekdays,
        skip_public_holidays=skip_public_holidays,
        skip_sunday_before_monday_ph=skip_sunday_before_monday_ph,
        rdo_dates=rdo_dates,
        include_dates=include_dates,
        exclude_dates=exclude_dates,
    )
    work_set = {date.fromisoformat(r["date"]) for r in work}
    end = date.fromisoformat(work[-1]["date"]) + timedelta(days=max(0, pad_days))
    holiday_names = holidays_between(works_start, end)
    rdo = rdo_dates or set()
    rows: list[dict[str, Any]] = []
    cursor = works_start
    while cursor <= end:
        ph_name = holiday_names.get(cursor)
        flags: list[str] = []
        if ph_name:
            flags.append("public_holiday")
        if cursor.weekday() == 5:
            flags.append("saturday")
        if cursor.weekday() == 6:
            flags.append("sunday")
        if cursor in rdo:
            flags.append("rdo")
        rows.append(
            {
                "date": cursor.isoformat(),
                "weekday": cursor.weekday(),
                "weekday_label": WEEKDAY_NAMES[cursor.weekday()],
                "rate_tier": classify_rate_tier(cursor, holiday_names=holiday_names),
                "flags": flags,
                "holiday_name": ph_name,
                "included": cursor in work_set,
            }
        )
        cursor += timedelta(days=1)
    return rows


def booking_label_for_pack(rate: Any) -> tuple[str, str]:
    """Return (short label, detail) for booking sheets."""
    n = int(getattr(rate, "pack_people", 1) or 0)
    tc = f"{n} TC"
    if getattr(rate, "includes_vehicle", False):
        return f"{tc} + vehicle", f"{n} TC{'s' if n != 1 else ''} with 1 vehicle"
    return f"{tc} (no vehicle)", f"{n} TC{'s' if n != 1 else ''} without vehicle"


def labour_cost_for_shift(
    *,
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
    crew: list[dict[str, Any]],
    rates_by_id: dict[int, Any],
    rate_tier: RateTier = "weekday",
) -> dict[str, Any]:
    """Legacy crew items: {rate_id, quantity}."""
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
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type, rate_tier)
        line_total = qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": rate_id,
                "name": rate.name,
                "rate_kind": getattr(rate, "rate_kind", "legacy"),
                "pack_people": getattr(rate, "pack_people", 1),
                "includes_vehicle": bool(getattr(rate, "includes_vehicle", False)),
                "quantity": qty,
                "shift_type": shift_type,
                "ordinary_hours": ordinary_h,
                "overtime_hours": ot_h,
                "ordinary_rate": money(ord_rate),
                "overtime_rate": money(ot_rate),
                "line_total": money(line_total),
            }
        )
    return {
        "lines": lines,
        "shift_labour_total": money(total),
        "allowances": empty_allowances(),
        "shift_total": money(total),
        "allocation": None,
        "booking_requirements": [],
        "booking_summary": "",
    }


def empty_allowances() -> dict[str, Any]:
    return {
        "heads": 0,
        "tc_heads": 0,
        "tma_drivers": 0,
        "spotter_heads": 0,
        "travel_per_head": 0.0,
        "meal_per_head": 0.0,
        "meal_after_hours": 9.5,
        "meals_apply": False,
        "travel_total": 0.0,
        "meal_total": 0.0,
        "allowances_total": 0.0,
        "note": "",
    }


def compute_allowances(
    *,
    tc_heads: int,
    tma_drivers: int,
    spotter_heads: int,
    shift_hours: float,
    travel_allowance: float,
    meal_allowance: float,
    meal_after_hours: float,
) -> dict[str, Any]:
    """Travel applies every shift; meals when shift length is over the threshold."""
    heads = max(0, tc_heads) + max(0, tma_drivers) + max(0, spotter_heads)
    meals_apply = shift_hours > float(meal_after_hours)
    travel_total = heads * float(travel_allowance)
    meal_total = heads * float(meal_allowance) if meals_apply else 0.0
    note = (
        f"Travel × {heads} heads (TCs + TMA drivers + spotters)."
        + (
            f" Meals × {heads} heads (shift {shift_hours:g}h > {meal_after_hours:g}h)."
            if meals_apply
            else f" No meals (shift {shift_hours:g}h is not over {meal_after_hours:g}h)."
        )
    )
    return {
        "heads": heads,
        "tc_heads": max(0, tc_heads),
        "tma_drivers": max(0, tma_drivers),
        "spotter_heads": max(0, spotter_heads),
        "travel_per_head": money(travel_allowance),
        "meal_per_head": money(meal_allowance),
        "meal_after_hours": float(meal_after_hours),
        "meals_apply": meals_apply,
        "travel_total": money(travel_total),
        "meal_total": money(meal_total),
        "allowances_total": money(travel_total + meal_total),
        "note": note,
    }


def allocate_resource_packs(
    *,
    people: int,
    vehicles: int,
    tmas: int,
    spotters: int = 0,
    rates: list[Any],
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
    travel_allowance: float = 0.0,
    meal_allowance: float = 0.0,
    meal_after_hours: float = 9.5,
    rate_tier: RateTier = "weekday",
) -> dict[str, Any]:
    """Cheapest crew-pack mix for TCs/vehicles, plus TMAs, spotters, and allowances.

    - Crew packs cover 1–4 TCs, optionally including one vehicle.
    - TMAs include their own drivers (not counted in the TC people total).
    - Spotters use their own rate and also receive travel/meals.
    - Travel applies per head each shift; meals when shift hours > threshold.
    """
    people = max(0, int(people))
    vehicles = max(0, int(vehicles))
    tmas = max(0, int(tmas))
    spotters = max(0, int(spotters))
    ordinary_h, ot_h = split_ordinary_ot(shift_hours, overtime_after)

    packs = [
        r
        for r in rates
        if getattr(r, "active", True) and getattr(r, "rate_kind", "") == "crew_pack"
    ]
    tma_rates = [
        r for r in rates if getattr(r, "active", True) and getattr(r, "rate_kind", "") == "tma"
    ]
    spotter_rates = [
        r
        for r in rates
        if getattr(r, "active", True) and getattr(r, "rate_kind", "") == "spotter"
    ]

    if (people > 0 or vehicles > 0) and not packs:
        raise ValueError(
            "No active crew pack rates configured. Add 1–4 TC packs (± vehicle) on the Rates page."
        )
    if tmas > 0 and not tma_rates:
        raise ValueError("No active TMA rates configured. Add a TMA rate on the Rates page.")
    if spotters > 0 and not spotter_rates:
        raise ValueError("No active Spotter rates configured. Add a Spotter rate on the Rates page.")

    pack_counts: dict[int, int] = {}
    covered_people = 0
    covered_vehicles = 0

    if people > 0 or vehicles > 0:
        # Min labour cost to cover at least P TCs and V vehicles (clamped unbounded knapsack).
        cost = [[INF] * (vehicles + 1) for _ in range(people + 1)]
        prev: list[list[tuple[int, int, int] | None]] = [
            [None] * (vehicles + 1) for _ in range(people + 1)
        ]
        cost[0][0] = 0.0

        pack_meta = []
        for r in packs:
            ppl = max(0, int(getattr(r, "pack_people", 1) or 0))
            veh = 1 if getattr(r, "includes_vehicle", False) else 0
            if ppl <= 0 and veh <= 0:
                continue
            uc = unit_shift_cost(
                r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h, rate_tier=rate_tier
            )
            pack_meta.append((r.id, ppl, veh, uc))

        if not pack_meta:
            raise ValueError("Crew pack rates must cover TCs and/or a vehicle")

        changed = True
        guard = (people + vehicles + 4) * max(1, len(pack_meta))
        while changed and guard > 0:
            guard -= 1
            changed = False
            for p in range(people + 1):
                for v in range(vehicles + 1):
                    base = cost[p][v]
                    if base >= INF:
                        continue
                    for rate_id, ppl, veh, uc in pack_meta:
                        np = min(people, p + ppl)
                        nv = min(vehicles, v + veh)
                        if np == p and nv == v:
                            continue
                        cand = base + uc
                        if cand < cost[np][nv] - 1e-9:
                            cost[np][nv] = cand
                            prev[np][nv] = (p, v, rate_id)
                            changed = True

        if cost[people][vehicles] >= INF:
            raise ValueError(
                "Cannot cover the requested TCs/vehicles with the configured pack rates. "
                "Ensure you have both with-vehicle and without-vehicle packs as needed."
            )

        p, v = people, vehicles
        while (p, v) != (0, 0):
            step = prev[p][v]
            if step is None:
                break
            op, ov, rate_id = step
            pack_counts[rate_id] = pack_counts.get(rate_id, 0) + 1
            p, v = op, ov

        rates_by_id_packs = {r.id: r for r in packs}
        for rate_id, qty in pack_counts.items():
            rate = rates_by_id_packs[rate_id]
            covered_people += qty * int(rate.pack_people)
            if rate.includes_vehicle:
                covered_vehicles += qty

    chosen_tma = None
    tma_qty = 0
    if tmas > 0:
        best = None
        for r in tma_rates:
            uc = unit_shift_cost(
                r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h, rate_tier=rate_tier
            )
            if best is None or uc < best[1]:
                best = (r, uc)
        assert best is not None
        chosen_tma, _uc = best
        tma_qty = tmas

    chosen_spotter = None
    spotter_qty = 0
    if spotters > 0:
        best = None
        for r in spotter_rates:
            uc = unit_shift_cost(
                r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h, rate_tier=rate_tier
            )
            if best is None or uc < best[1]:
                best = (r, uc)
        assert best is not None
        chosen_spotter, _uc = best
        spotter_qty = spotters

    rates_by_id = {r.id: r for r in rates}
    lines: list[dict[str, Any]] = []
    booking: list[dict[str, Any]] = []
    total = 0.0

    for rate_id, qty in sorted(
        pack_counts.items(),
        key=lambda x: (
            -int(rates_by_id[x[0]].pack_people),
            not rates_by_id[x[0]].includes_vehicle,
            rates_by_id[x[0]].position,
        ),
    ):
        rate = rates_by_id[rate_id]
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type, rate_tier)
        line_total = qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        short, detail = booking_label_for_pack(rate)
        lines.append(
            {
                "rate_id": rate_id,
                "name": rate.name,
                "booking_label": short,
                "booking_detail": detail,
                "rate_kind": "crew_pack",
                "pack_people": int(rate.pack_people),
                "includes_vehicle": bool(rate.includes_vehicle),
                "quantity": qty,
                "people_covered": qty * int(rate.pack_people),
                "vehicles_covered": qty if rate.includes_vehicle else 0,
                "shift_type": shift_type,
                "ordinary_hours": ordinary_h,
                "overtime_hours": ot_h,
                "ordinary_rate": money(ord_rate),
                "overtime_rate": money(ot_rate),
                "line_total": money(line_total),
            }
        )
        booking.append(
            {
                "quantity": qty,
                "rate_id": rate_id,
                "rate_kind": "crew_pack",
                "label": short,
                "detail": detail,
                "text": f"{qty}× {short} ({detail})",
            }
        )

    if chosen_tma and tma_qty:
        ord_rate, ot_rate = rate_unit_rates(chosen_tma, shift_type, rate_tier)
        line_total = tma_qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": chosen_tma.id,
                "name": chosen_tma.name,
                "booking_label": "TMA (incl. driver)",
                "booking_detail": "TMA unit with driver — driver not counted in TC total",
                "rate_kind": "tma",
                "pack_people": 0,
                "includes_vehicle": True,
                "quantity": tma_qty,
                "people_covered": 0,
                "vehicles_covered": 0,
                "note": "TMA includes driver — not counted in assigned TCs",
                "shift_type": shift_type,
                "ordinary_hours": ordinary_h,
                "overtime_hours": ot_h,
                "ordinary_rate": money(ord_rate),
                "overtime_rate": money(ot_rate),
                "line_total": money(line_total),
            }
        )
        booking.append(
            {
                "quantity": tma_qty,
                "rate_id": chosen_tma.id,
                "rate_kind": "tma",
                "label": "TMA (incl. driver)",
                "detail": "includes driver",
                "text": f"{tma_qty}× TMA (incl. driver)",
            }
        )

    if chosen_spotter and spotter_qty:
        ord_rate, ot_rate = rate_unit_rates(chosen_spotter, shift_type, rate_tier)
        line_total = spotter_qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": chosen_spotter.id,
                "name": chosen_spotter.name,
                "booking_label": "Spotter",
                "booking_detail": "Spotter — own rate; meals & travel apply",
                "rate_kind": "spotter",
                "pack_people": 1,
                "includes_vehicle": False,
                "quantity": spotter_qty,
                "people_covered": 0,
                "vehicles_covered": 0,
                "note": "Spotter uses own rate; receives travel and meals",
                "shift_type": shift_type,
                "ordinary_hours": ordinary_h,
                "overtime_hours": ot_h,
                "ordinary_rate": money(ord_rate),
                "overtime_rate": money(ot_rate),
                "line_total": money(line_total),
            }
        )
        booking.append(
            {
                "quantity": spotter_qty,
                "rate_id": chosen_spotter.id,
                "rate_kind": "spotter",
                "label": "Spotter",
                "detail": "own rate; meals & travel apply",
                "text": f"{spotter_qty}× Spotter",
            }
        )

    allowances = compute_allowances(
        tc_heads=people,
        tma_drivers=tmas,
        spotter_heads=spotters,
        shift_hours=shift_hours,
        travel_allowance=travel_allowance,
        meal_allowance=meal_allowance,
        meal_after_hours=meal_after_hours,
    )
    labour_total = money(total)
    shift_total = money(labour_total + allowances["allowances_total"])
    booking_summary = "; ".join(b["text"] for b in booking) if booking else "No crew booked"

    spare_tc = max(0, covered_people - people)
    note = (
        "Cheapest pack mix for the requested TCs and vehicles. "
        "TMAs and spotters are billed on their own rates. "
        "Travel applies to TCs, TMA drivers and spotters; meals when shift is over the meal threshold."
    )
    if spare_tc:
        note += f" Booking covers {covered_people} TC seats ({spare_tc} above request) because that pack mix is cheaper."

    return {
        "lines": lines,
        "shift_labour_total": labour_total,
        "allowances": allowances,
        "shift_total": shift_total,
        "booking_requirements": booking,
        "booking_summary": booking_summary,
        "allocation": {
            "requested": {
                "people": people,
                "vehicles": vehicles,
                "tmas": tmas,
                "spotters": spotters,
            },
            "covered": {
                "people": covered_people,
                "vehicles": covered_vehicles,
                "tmas": tmas,
                "spotters": spotters,
            },
            "pack_units": sum(pack_counts.values()),
            "tma_rate_id": chosen_tma.id if chosen_tma else None,
            "spotter_rate_id": chosen_spotter.id if chosen_spotter else None,
            "note": note,
        },
    }


def settings_allowance_values(settings: Any, payload: dict[str, Any]) -> tuple[float, float, float]:
    travel = float(
        payload.get(
            "travel_allowance",
            getattr(settings, "travel_allowance", 0.0),
        )
    )
    meal = float(
        payload.get(
            "meal_allowance",
            getattr(settings, "meal_allowance", 0.0),
        )
    )
    meal_after = float(
        payload.get(
            "meal_after_hours",
            getattr(settings, "meal_after_hours", 9.5),
        )
    )
    return travel, meal, meal_after


def resolve_shift_labour(
    payload: dict[str, Any],
    *,
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
    rates: list[Any],
    settings: Any = None,
    rate_tier: RateTier = "weekday",
) -> dict[str, Any]:
    """Prefer resource allocation when people/vehicles/tmas/spotters supplied."""
    resources = payload.get("resources")
    if resources is None and any(
        k in payload for k in ("people", "vehicles", "tmas", "spotters")
    ):
        resources = {
            "people": payload.get("people", 0),
            "vehicles": payload.get("vehicles", 0),
            "tmas": payload.get("tmas", 0),
            "spotters": payload.get("spotters", 0),
        }
    if resources is not None:
        travel, meal, meal_after = settings_allowance_values(settings or object(), payload)
        return allocate_resource_packs(
            people=int(resources.get("people") or 0),
            vehicles=int(resources.get("vehicles") or 0),
            tmas=int(resources.get("tmas") or 0),
            spotters=int(resources.get("spotters") or 0),
            rates=rates,
            shift_hours=shift_hours,
            shift_type=shift_type,
            overtime_after=overtime_after,
            travel_allowance=travel,
            meal_allowance=meal,
            meal_after_hours=meal_after,
            rate_tier=rate_tier,
        )
    rates_by_id = {r.id: r for r in rates}
    return labour_cost_for_shift(
        shift_hours=shift_hours,
        shift_type=shift_type,
        overtime_after=overtime_after,
        crew=payload.get("crew") or [],
        rates_by_id=rates_by_id,
        rate_tier=rate_tier,
    )


def vms_calendar_days(
    *,
    lead_days: int,
    works_start: date,
    works_end: date,
) -> dict[str, Any]:
    """VMS out `lead_days` before works start, through works end date (inclusive)."""
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


def shift_extras_cost(items: Any, total_shifts: int) -> dict[str, Any]:
    """Plant billed per shift: quantity × unit rate × total shifts (no delivery)."""
    shifts = max(0, int(total_shifts or 0))
    lines: list[dict[str, Any]] = []
    total = 0.0
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        qty = float(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        rate = float(raw.get("unit_rate") or 0)
        name = (raw.get("name") or "Extra").strip() or "Extra"
        line_total = qty * rate * shifts
        total += line_total
        lines.append(
            {
                "extra_id": raw.get("extra_id") or raw.get("id"),
                "name": name,
                "quantity": qty,
                "unit_rate": money(rate),
                "shifts": shifts,
                "line_total": money(line_total),
                "basis": "qty × rate × shifts",
            }
        )
    return {
        "lines": lines,
        "shifts": shifts,
        "extras_total": money(total),
        "note": "Per-shift items (arrowboard, etc.): quantity × unit rate × total shifts. No pickup or delivery.",
    }


def _shift_type_for_date(
    work_date: date,
    *,
    shift_start_time: str | None,
    shift_hours: float,
    forced: ShiftType | None,
    day_start: float,
    day_end: float,
) -> ShiftType:
    if forced in ("day", "night"):
        return forced  # type: ignore[return-value]
    if not shift_start_time:
        return "day"
    try:
        parts = [int(p) for p in str(shift_start_time).split(":")[:2]]
        hh, mm = parts[0], parts[1] if len(parts) > 1 else 0
    except (TypeError, ValueError) as exc:
        raise ValueError("shift_start_time must be HH:MM") from exc
    mid = datetime.combine(work_date, datetime.min.time()).replace(
        hour=hh, minute=mm
    ) + timedelta(hours=shift_hours / 2)
    return classify_shift_type(mid, day_start_hour=day_start, day_end_hour=day_end)


def calculate_standard(payload: dict[str, Any], settings: Any, rates: list[Any]) -> dict[str, Any]:
    overtime_after = float(
        payload.get("overtime_after_hours", settings.overtime_after_hours)
    )
    shift_hours = float(payload["shift_hours"])
    day_start = float(getattr(settings, "day_start_hour", 6.0) or 6.0)
    day_end = float(getattr(settings, "day_end_hour", 18.0) or 18.0)
    if "day_start_hour" in payload:
        day_start = float(payload["day_start_hour"])
    if "day_end_hour" in payload:
        day_end = float(payload["day_end_hour"])

    works_start = date.fromisoformat(payload["works_start"])
    days_of_work = payload.get("days_of_work")
    shifts_per_day = int(payload.get("shifts_per_day") or 1)
    if shifts_per_day <= 0:
        raise ValueError("shifts_per_day must be positive")

    shift_start_time = payload.get("shift_start_time")
    shift_type_raw = payload.get("shift_type")
    forced_type: ShiftType | None = shift_type_raw if shift_type_raw in ("day", "night") else None

    use_schedule = any(
        k in payload
        for k in (
            "work_weekdays",
            "work_dates",
            "skip_public_holidays",
            "skip_sunday_before_monday_ph",
            "rdo_dates",
            "include_dates",
            "exclude_dates",
        )
    )

    schedule_rows: list[dict[str, Any]] = []
    if payload.get("work_dates"):
        holiday_names = holidays_between(
            works_start, works_start + timedelta(days=400)
        )
        for raw in payload["work_dates"]:
            d = date.fromisoformat(str(raw)[:10])
            schedule_rows.append(
                {
                    "date": d.isoformat(),
                    "weekday": d.weekday(),
                    "weekday_label": WEEKDAY_NAMES[d.weekday()],
                    "rate_tier": classify_rate_tier(d, holiday_names=holiday_names),
                    "flags": ["public_holiday"] if d in holiday_names else [],
                    "holiday_name": holiday_names.get(d),
                    "included": True,
                }
            )
        schedule_rows.sort(key=lambda r: r["date"])
        if not schedule_rows:
            raise ValueError("work_dates must include at least one date")
        days_of_work = len(schedule_rows)
        works_end = date.fromisoformat(schedule_rows[-1]["date"])
        works_start = date.fromisoformat(schedule_rows[0]["date"])
    elif use_schedule:
        if days_of_work is None:
            raise ValueError("days_of_work is required with a work-day pattern")
        days_of_work = int(days_of_work)
        weekdays = payload.get("work_weekdays")
        if weekdays is not None:
            weekdays = [int(x) for x in weekdays]
        schedule_rows = build_work_schedule(
            works_start,
            days_of_work,
            work_weekdays=weekdays,
            skip_public_holidays=bool(payload.get("skip_public_holidays", True)),
            skip_sunday_before_monday_ph=bool(
                payload.get("skip_sunday_before_monday_ph", True)
            ),
            rdo_dates=parse_date_list(payload.get("rdo_dates")),
            include_dates=parse_date_list(payload.get("include_dates")),
            exclude_dates=parse_date_list(payload.get("exclude_dates")),
        )
        works_end = date.fromisoformat(schedule_rows[-1]["date"])
    else:
        # Legacy contiguous calendar days
        if days_of_work is not None:
            days_of_work = int(days_of_work)
            if days_of_work <= 0:
                raise ValueError("days_of_work must be positive")
            works_end = works_start + timedelta(days=days_of_work - 1)
        else:
            works_end = date.fromisoformat(payload.get("works_end") or payload["works_start"])
            if works_end < works_start:
                raise ValueError("works_end must be on or after works_start")
            days_of_work = (works_end - works_start).days + 1
        cursor = works_start
        while cursor <= works_end:
            schedule_rows.append(
                {
                    "date": cursor.isoformat(),
                    "weekday": cursor.weekday(),
                    "weekday_label": WEEKDAY_NAMES[cursor.weekday()],
                    "rate_tier": "weekday",
                    "flags": [],
                    "holiday_name": None,
                    "included": True,
                }
            )
            cursor += timedelta(days=1)

    total_shifts = days_of_work * shifts_per_day
    if shift_hours <= 0 or total_shifts <= 0:
        raise ValueError("shift_hours and total_shifts must be positive")

    # Representative shift type (first work day) for booking echo / legacy clients
    first_date = date.fromisoformat(schedule_rows[0]["date"])
    shift_type = _shift_type_for_date(
        first_date,
        shift_start_time=shift_start_time,
        shift_hours=shift_hours,
        forced=forced_type,
        day_start=day_start,
        day_end=day_end,
    )

    labour_cache: dict[tuple[ShiftType, RateTier], dict[str, Any]] = {}
    site_labour = 0.0
    site_allowances = 0.0
    site_crew = 0.0
    day_breakdown: list[dict[str, Any]] = []

    for row in schedule_rows:
        d = date.fromisoformat(row["date"])
        tier: RateTier = row["rate_tier"]  # type: ignore[assignment]
        st = _shift_type_for_date(
            d,
            shift_start_time=shift_start_time,
            shift_hours=shift_hours,
            forced=forced_type,
            day_start=day_start,
            day_end=day_end,
        )
        key = (st, tier)
        if key not in labour_cache:
            labour_cache[key] = resolve_shift_labour(
                payload,
                shift_hours=shift_hours,
                shift_type=st,
                overtime_after=overtime_after,
                rates=rates,
                settings=settings,
                rate_tier=tier,
            )
        labour = labour_cache[key]
        day_crew = labour["shift_total"] * shifts_per_day
        day_labour = labour["shift_labour_total"] * shifts_per_day
        day_allow = labour["allowances"]["allowances_total"] * shifts_per_day
        site_crew += day_crew
        site_labour += day_labour
        site_allowances += day_allow
        day_breakdown.append(
            {
                **row,
                "shift_type": st,
                "shifts": shifts_per_day,
                "shift_total": money(labour["shift_total"]),
                "day_total": money(day_crew),
            }
        )

    # Booking sheet from the most common / first labour profile
    labour = labour_cache.get((shift_type, schedule_rows[0]["rate_tier"]), next(iter(labour_cache.values())))

    lead_days = int(payload.get("vms_lead_days", settings.vms_lead_days_default))
    vms_qty = int(payload.get("vms_quantity") or 0)
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

    extras = shift_extras_cost(payload.get("shift_extras"), total_shifts)
    grand = site_crew + vms["vms_total"] + extras["extras_total"]
    return {
        "mode": "standard",
        "inputs_echo": {
            "shift_hours": shift_hours,
            "shift_type": shift_type,
            "shift_start_time": shift_start_time,
            "days_of_work": days_of_work,
            "shifts_per_day": shifts_per_day,
            "total_shifts": total_shifts,
            "overtime_after_hours": overtime_after,
            "works_start": works_start.isoformat(),
            "works_end": works_end.isoformat(),
            "day_start_hour": day_start,
            "day_end_hour": day_end,
            "work_weekdays": payload.get("work_weekdays"),
            "skip_public_holidays": bool(payload.get("skip_public_holidays", True))
            if use_schedule or payload.get("work_dates")
            else False,
            "skip_sunday_before_monday_ph": bool(
                payload.get("skip_sunday_before_monday_ph", True)
            )
            if use_schedule or payload.get("work_dates")
            else False,
            "rdo_dates": sorted(str(x) for x in parse_date_list(payload.get("rdo_dates"))),
            "resources": (labour.get("allocation") or {}).get("requested"),
            "shift_extras": extras["lines"],
        },
        "schedule": day_breakdown,
        "per_shift": labour,
        "booking_requirements": labour.get("booking_requirements") or [],
        "booking_summary": labour.get("booking_summary") or "",
        "site_labour_total": money(site_labour),
        "site_allowances_total": money(site_allowances),
        "site_crew_total": money(site_crew),
        "vms": vms,
        "shift_extras": extras,
        "site_traffic_total": money(grand),
    }


def _shift_type_sequence(
    start: datetime,
    shift_hours: float,
    count: int,
    *,
    day_start_hour: float = 6.0,
    day_end_hour: float = 18.0,
) -> list[ShiftType]:
    """Classify each back-to-back shift as day or night from midpoint vs configured window."""
    types: list[ShiftType] = []
    cursor = start
    for _ in range(count):
        mid = cursor + timedelta(hours=shift_hours / 2)
        types.append(
            classify_shift_type(mid, day_start_hour=day_start_hour, day_end_hour=day_end_hour)
        )
        cursor += timedelta(hours=shift_hours)
    return types


def _closure_option(
    *,
    label: str,
    shift_hours: float,
    start: datetime,
    end: datetime,
    overtime_after: float,
    payload: dict[str, Any],
    rates: list[Any],
    settings: Any,
) -> dict[str, Any]:
    duration_h = (end - start).total_seconds() / 3600
    if duration_h <= 0:
        raise ValueError("closure end must be after start")
    shifts = int(math.ceil(duration_h / shift_hours - 1e-9))
    day_start = float(
        payload.get("day_start_hour", getattr(settings, "day_start_hour", 6.0) or 6.0)
    )
    day_end = float(
        payload.get("day_end_hour", getattr(settings, "day_end_hour", 18.0) or 18.0)
    )
    types = _shift_type_sequence(
        start,
        shift_hours,
        shifts,
        day_start_hour=day_start,
        day_end_hour=day_end,
    )

    per_shift = []
    pack_labour_total = 0.0
    travel_total = 0.0
    meal_total = 0.0
    allowances_total = 0.0
    crew_total = 0.0
    day_shifts = 0
    night_shifts = 0
    allocation = None
    booking_requirements = []
    booking_summary = ""
    sample_allowances = empty_allowances()
    for idx, stype in enumerate(types):
        detail = resolve_shift_labour(
            payload,
            shift_hours=shift_hours,
            shift_type=stype,
            overtime_after=overtime_after,
            rates=rates,
            settings=settings,
        )
        allow = detail.get("allowances") or empty_allowances()
        pack_labour_total += detail["shift_labour_total"]
        travel_total += allow["travel_total"]
        meal_total += allow["meal_total"]
        allowances_total += allow["allowances_total"]
        crew_total += detail["shift_total"]
        if stype == "day":
            day_shifts += 1
        else:
            night_shifts += 1
        if allocation is None:
            allocation = detail.get("allocation")
            booking_requirements = detail.get("booking_requirements") or []
            booking_summary = detail.get("booking_summary") or ""
            sample_allowances = allow
        per_shift.append(
            {
                "index": idx + 1,
                "shift_type": stype,
                "hours": shift_hours,
                "labour_total": detail["shift_labour_total"],
                "travel_total": allow["travel_total"],
                "meal_total": allow["meal_total"],
                "allowances_total": allow["allowances_total"],
                "meals_apply": allow["meals_apply"],
                "shift_total": detail["shift_total"],
                "lines": detail["lines"],
                "allowances": allow,
            }
        )

    return {
        "label": label,
        "key": "3x8" if shift_hours == 8 else "2x12" if shift_hours == 12 else f"{shift_hours:g}h",
        "shift_hours": shift_hours,
        "shifts_required": shifts,
        "day_shifts": day_shifts,
        "night_shifts": night_shifts,
        "duration_hours": money(duration_h),
        # pack/TMA/spotter labour only
        "pack_labour_total": money(pack_labour_total),
        "travel_total": money(travel_total),
        "meal_total": money(meal_total),
        "allowances_total": money(allowances_total),
        # crew = pack labour + travel + meals (kept as labour_total for compatibility)
        "crew_total": money(crew_total),
        "labour_total": money(crew_total),
        "meals_apply_per_shift": bool(sample_allowances.get("meals_apply")),
        "sample_allowances": sample_allowances,
        "allocation": allocation,
        "booking_requirements": booking_requirements,
        "booking_summary": booking_summary,
        "per_shift": per_shift,
        "is_best": False,
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

    opt_3x8 = _closure_option(
        label="3 × 8-hour shifts (per 24h coverage)",
        shift_hours=8,
        start=start,
        end=end,
        overtime_after=overtime_after,
        payload=payload,
        rates=rates,
        settings=settings,
    )
    opt_2x12 = _closure_option(
        label="2 × 12-hour shifts (per 24h coverage)",
        shift_hours=12,
        start=start,
        end=end,
        overtime_after=overtime_after,
        payload=payload,
        rates=rates,
        settings=settings,
    )

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
        extras = shift_extras_cost(payload.get("shift_extras"), opt["shifts_required"])
        opt["shift_extras"] = extras
        opt["extras_total"] = extras["extras_total"]
        opt["vms_total"] = vms["vms_total"]
        opt["grand_total"] = money(opt["crew_total"] + vms["vms_total"] + extras["extras_total"])

    if opt_3x8["grand_total"] < opt_2x12["grand_total"]:
        cheaper = "3x8"
        opt_3x8["is_best"] = True
        best_label = "3 × 8-hour shifts"
    elif opt_2x12["grand_total"] < opt_3x8["grand_total"]:
        cheaper = "2x12"
        opt_2x12["is_best"] = True
        best_label = "2 × 12-hour shifts"
    else:
        cheaper = "equal"
        opt_3x8["is_best"] = True
        opt_2x12["is_best"] = True
        best_label = "Either pattern (equal cost)"

    saving = money(abs(opt_3x8["grand_total"] - opt_2x12["grand_total"]))
    meal_note_8 = (
        "no meals"
        if not opt_3x8["meals_apply_per_shift"]
        else f"meals ${opt_3x8['meal_total']:,.2f}"
    )
    meal_note_12 = (
        "no meals"
        if not opt_2x12["meals_apply_per_shift"]
        else f"meals ${opt_2x12['meal_total']:,.2f}"
    )

    return {
        "mode": "closure_24h",
        "inputs_echo": {
            "closure_start": start.isoformat(sep=" "),
            "closure_end": end.isoformat(sep=" "),
            "overtime_after_hours": overtime_after,
            "duration_hours": money((end - start).total_seconds() / 3600),
            "resources": (opt_3x8.get("allocation") or {}).get("requested"),
        },
        "vms": vms,
        "shift_extras": opt_3x8.get("shift_extras"),
        "option_3x8": opt_3x8,
        "option_2x12": opt_2x12,
        "booking_requirements": opt_3x8.get("booking_requirements") or [],
        "booking_summary": opt_3x8.get("booking_summary") or "",
        "recommendation": {
            "cheaper": cheaper,
            "best_key": cheaper,
            "best_label": best_label,
            "saving": saving,
            "summary": (
                f"BEST: {best_label}. "
                f"8h pattern ${opt_3x8['grand_total']:,.2f} "
                f"(pack ${opt_3x8['pack_labour_total']:,.2f} + travel ${opt_3x8['travel_total']:,.2f} "
                f"+ {meal_note_8} + VMS ${opt_3x8['vms_total']:,.2f} + extras ${opt_3x8['extras_total']:,.2f}) vs "
                f"12h pattern ${opt_2x12['grand_total']:,.2f} "
                f"(pack ${opt_2x12['pack_labour_total']:,.2f} + travel ${opt_2x12['travel_total']:,.2f} "
                f"+ {meal_note_12} + VMS ${opt_2x12['vms_total']:,.2f} + extras ${opt_2x12['extras_total']:,.2f})"
                + (f". Saves ${saving:,.2f}." if cheaper != "equal" else ".")
                + " Travel applies every shift; meals only when shift length exceeds the meal threshold."
            ),
        },
    }
