"""Traffic management cost calculations: resource packs, shifts, VMS, 24h compare."""

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
    return {"lines": lines, "shift_labour_total": money(total), "allocation": None}


def allocate_resource_packs(
    *,
    people: int,
    vehicles: int,
    tmas: int,
    rates: list[Any],
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
) -> dict[str, Any]:
    """Choose the cheapest combination of crew packs + TMAs for the resources.

    - Crew packs cover 1–4 people, optionally including one vehicle.
    - TMAs are separate units that include their own drivers (do not consume
      from the people count).
    """
    people = max(0, int(people))
    vehicles = max(0, int(vehicles))
    tmas = max(0, int(tmas))
    ordinary_h, ot_h = split_ordinary_ot(shift_hours, overtime_after)

    packs = [
        r
        for r in rates
        if getattr(r, "active", True) and getattr(r, "rate_kind", "") == "crew_pack"
    ]
    tma_rates = [
        r for r in rates if getattr(r, "active", True) and getattr(r, "rate_kind", "") == "tma"
    ]

    if (people > 0 or vehicles > 0) and not packs:
        raise ValueError(
            "No active crew pack rates configured. Add 1–4 person packs (± vehicle) on the Rates page."
        )
    if tmas > 0 and not tma_rates:
        raise ValueError("No active TMA rates configured. Add a TMA rate on the Rates page.")

    pack_counts: dict[int, int] = {}
    pack_cost = 0.0
    covered_people = 0
    covered_vehicles = 0

    if people > 0 or vehicles > 0:
        # Clamped unbounded knapsack: min cost to cover at least P people and V vehicles.
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
            raise ValueError("Crew pack rates must cover people and/or a vehicle")

        changed = True
        # Enough passes for unbounded combinations (people+vehicles bound)
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
                        if cand < cost[np][nv]:
                            cost[np][nv] = cand
                            prev[np][nv] = (p, v, rate_id)
                            changed = True

        if cost[people][vehicles] >= INF:
            raise ValueError(
                "Cannot cover the requested people/vehicles with the configured pack rates. "
                "Ensure you have both with-vehicle and without-vehicle packs as needed."
            )

        # Reconstruct pack multiset
        p, v = people, vehicles
        while (p, v) != (0, 0):
            step = prev[p][v]
            if step is None:
                break
            op, ov, rate_id = step
            pack_counts[rate_id] = pack_counts.get(rate_id, 0) + 1
            p, v = op, ov
        pack_cost = float(cost[people][vehicles])

        rates_by_id = {r.id: r for r in packs}
        for rate_id, qty in pack_counts.items():
            rate = rates_by_id[rate_id]
            covered_people += qty * int(rate.pack_people)
            if rate.includes_vehicle:
                covered_vehicles += qty

    # TMAs — pick cheapest TMA rate card (driver included in the rate)
    tma_lines = []
    tma_cost = 0.0
    chosen_tma = None
    if tmas > 0:
        best = None
        for r in tma_rates:
            uc = unit_shift_cost(r, shift_type=shift_type, ordinary_h=ordinary_h, ot_h=ot_h)
            if best is None or uc < best[1]:
                best = (r, uc)
        assert best is not None
        chosen_tma, uc = best
        tma_cost = tmas * uc
        tma_lines.append((chosen_tma, tmas, uc))

    rates_by_id = {r.id: r for r in rates}
    lines = []
    total = 0.0

    for rate_id, qty in sorted(pack_counts.items(), key=lambda x: rates_by_id[x[0]].position):
        rate = rates_by_id[rate_id]
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type)
        line_total = qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": rate_id,
                "name": rate.name,
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

    for rate, qty, _uc in tma_lines:
        ord_rate, ot_rate = rate_unit_rates(rate, shift_type)
        line_total = qty * (ordinary_h * ord_rate + ot_h * ot_rate)
        total += line_total
        lines.append(
            {
                "rate_id": rate.id,
                "name": rate.name,
                "rate_kind": "tma",
                "pack_people": 0,
                "includes_vehicle": True,
                "quantity": qty,
                "people_covered": 0,
                "vehicles_covered": 0,
                "note": "TMA includes driver — not counted in assigned people",
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
        "allocation": {
            "requested": {"people": people, "vehicles": vehicles, "tmas": tmas},
            "covered": {
                "people": covered_people,
                "vehicles": covered_vehicles,
                "tmas": tmas,
            },
            "pack_units": sum(pack_counts.values()),
            "tma_rate_id": chosen_tma.id if chosen_tma else None,
            "note": (
                "Best-cost mix of configured crew packs for people/vehicles. "
                "TMAs billed separately (driver included)."
            ),
        },
    }


def resolve_shift_labour(
    payload: dict[str, Any],
    *,
    shift_hours: float,
    shift_type: ShiftType,
    overtime_after: float,
    rates: list[Any],
) -> dict[str, Any]:
    """Prefer resource allocation when people/vehicles/tmas supplied; else legacy crew."""
    resources = payload.get("resources")
    if resources is None and any(k in payload for k in ("people", "vehicles", "tmas")):
        resources = {
            "people": payload.get("people", 0),
            "vehicles": payload.get("vehicles", 0),
            "tmas": payload.get("tmas", 0),
        }
    if resources is not None:
        return allocate_resource_packs(
            people=int(resources.get("people") or 0),
            vehicles=int(resources.get("vehicles") or 0),
            tmas=int(resources.get("tmas") or 0),
            rates=rates,
            shift_hours=shift_hours,
            shift_type=shift_type,
            overtime_after=overtime_after,
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
            "resources": labour.get("allocation", {}).get("requested")
            if labour.get("allocation")
            else None,
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
) -> dict[str, Any]:
    duration_h = (end - start).total_seconds() / 3600
    if duration_h <= 0:
        raise ValueError("closure end must be after start")
    shifts = int(math.ceil(duration_h / shift_hours - 1e-9))
    types = _shift_type_sequence(start, shift_hours, shifts)

    per_shift = []
    labour_total = 0.0
    day_shifts = 0
    night_shifts = 0
    allocation = None
    for idx, stype in enumerate(types):
        detail = resolve_shift_labour(
            payload,
            shift_hours=shift_hours,
            shift_type=stype,
            overtime_after=overtime_after,
            rates=rates,
        )
        labour_total += detail["shift_labour_total"]
        if stype == "day":
            day_shifts += 1
        else:
            night_shifts += 1
        if allocation is None:
            allocation = detail.get("allocation")
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
        "allocation": allocation,
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
    )
    opt_2x12 = _closure_option(
        label="2 × 12-hour shifts (per 24h coverage)",
        shift_hours=12,
        start=start,
        end=end,
        overtime_after=overtime_after,
        payload=payload,
        rates=rates,
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
            "resources": opt_3x8.get("allocation", {}).get("requested")
            if opt_3x8.get("allocation")
            else None,
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
