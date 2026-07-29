"""Traffic management cost calculations: TC packs, allowances, VMS, 24h compare."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Literal

ShiftType = Literal["day", "night"]

INF = 10**18


def money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def split_ordinary_ot(shift_hours: float, overtime_after: float) -> tuple[float, float]:
    ordinary = min(shift_hours, overtime_after)
    ot = max(0.0, shift_hours - overtime_after)
    return ordinary, ot


def unit_shift_cost(rate: Any, *, shift_type: ShiftType, ordinary_h: float, ot_h: float) -> float:
    if shift_type == "night":
        ord_rate = float(rate.night_ordinary)
        ot_rate = float(rate.night_overtime)
    else:
        ord_rate = float(rate.day_ordinary)
        ot_rate = float(rate.day_overtime)
    return ordinary_h * ord_rate + ot_h * ot_rate


def rate_unit_rates(rate: Any, shift_type: ShiftType) -> tuple[float, float]:
    if shift_type == "night":
        return float(rate.night_ordinary), float(rate.night_overtime)
    return float(rate.day_ordinary), float(rate.day_overtime)


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
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type)
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
            uc = unit_shift_cost(r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h)
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
            uc = unit_shift_cost(r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h)
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
            uc = unit_shift_cost(r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h)
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
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type)
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
        ord_rate, ot_rate = rate_unit_rates(chosen_tma, shift_type)
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
        ord_rate, ot_rate = rate_unit_rates(chosen_spotter, shift_type)
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
        )
    rates_by_id = {r.id: r for r in rates}
    return labour_cost_for_shift(
        shift_hours=shift_hours,
        shift_type=shift_type,
        overtime_after=overtime_after,
        crew=payload.get("crew") or [],
        rates_by_id=rates_by_id,
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

    labour = resolve_shift_labour(
        payload,
        shift_hours=shift_hours,
        shift_type=shift_type,
        overtime_after=overtime_after,
        rates=rates,
        settings=settings,
    )
    site_labour = labour["shift_labour_total"] * total_shifts
    site_allowances = labour["allowances"]["allowances_total"] * total_shifts
    site_crew = labour["shift_total"] * total_shifts
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

    grand = site_crew + vms["vms_total"]
    return {
        "mode": "standard",
        "inputs_echo": {
            "shift_hours": shift_hours,
            "shift_type": shift_type,
            "total_shifts": total_shifts,
            "overtime_after_hours": overtime_after,
            "works_start": works_start.isoformat(),
            "works_end": works_end.isoformat(),
            "resources": (labour.get("allocation") or {}).get("requested"),
        },
        "per_shift": labour,
        "booking_requirements": labour.get("booking_requirements") or [],
        "booking_summary": labour.get("booking_summary") or "",
        "site_labour_total": money(site_labour),
        "site_allowances_total": money(site_allowances),
        "site_crew_total": money(site_crew),
        "vms": vms,
        "site_traffic_total": money(grand),
    }


def _shift_type_sequence(start: datetime, shift_hours: float, count: int) -> list[ShiftType]:
    """Classify each back-to-back shift as day (06:00–18:00) or night."""
    types: list[ShiftType] = []
    cursor = start
    for _ in range(count):
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
    payload: dict[str, Any],
    rates: list[Any],
    settings: Any,
) -> dict[str, Any]:
    duration_h = (end - start).total_seconds() / 3600
    if duration_h <= 0:
        raise ValueError("closure end must be after start")
    shifts = int(math.ceil(duration_h / shift_hours - 1e-9))
    types = _shift_type_sequence(start, shift_hours, shifts)

    per_shift = []
    labour_total = 0.0
    allowances_total = 0.0
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
        labour_total += detail["shift_total"]
        allowances_total += detail["allowances"]["allowances_total"]
        if stype == "day":
            day_shifts += 1
        else:
            night_shifts += 1
        if allocation is None:
            allocation = detail.get("allocation")
            booking_requirements = detail.get("booking_requirements") or []
            booking_summary = detail.get("booking_summary") or ""
            sample_allowances = detail.get("allowances") or empty_allowances()
        per_shift.append(
            {
                "index": idx + 1,
                "shift_type": stype,
                "hours": shift_hours,
                "labour_total": detail["shift_labour_total"],
                "allowances_total": detail["allowances"]["allowances_total"],
                "shift_total": detail["shift_total"],
                "lines": detail["lines"],
                "allowances": detail.get("allowances"),
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
        "allowances_total": money(allowances_total),
        "sample_allowances": sample_allowances,
        "allocation": allocation,
        "booking_requirements": booking_requirements,
        "booking_summary": booking_summary,
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
            "resources": (opt_3x8.get("allocation") or {}).get("requested"),
        },
        "vms": vms,
        "option_3x8": opt_3x8,
        "option_2x12": opt_2x12,
        "booking_requirements": opt_3x8.get("booking_requirements") or [],
        "booking_summary": opt_3x8.get("booking_summary") or "",
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
                + " VMS charged by calendar day (not per shift). "
                + "Meals apply on shifts over the meal threshold (typically 12h, not 8h)."
            ),
        },
    }
