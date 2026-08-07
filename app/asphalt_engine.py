"""Asphalt cost calculation helpers."""

from __future__ import annotations

from typing import Any


def pick_tier_rate(rate_row: dict[str, Any], tier: str) -> float:
    """Return the unit rate for a calendar tier, falling back sensibly."""
    day = float(rate_row.get("day_rate") or 0)
    night = float(rate_row.get("night_rate") or 0) or day
    saturday = float(rate_row.get("saturday_rate") or 0) or night or day
    sunday = float(rate_row.get("sunday_rate") or 0) or saturday
    ph = float(rate_row.get("public_holiday_rate") or 0) or sunday
    if tier == "public_holiday":
        return ph
    if tier == "sunday":
        return sunday
    if tier == "saturday":
        return saturday
    if tier == "night":
        return night
    return day


def calculate_asphalt(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate asphalt line totals.

    Expected payload keys:
      - shift_type: day|night (default day) — applies when no per-line schedule
      - rate_tier: weekday|saturday|sunday|public_holiday|night (optional override)
      - lines: [{ rate_id?, name, unit, quantity, day_rate, night_rate, ... }]
    """
    lines_in = payload.get("lines") or []
    if not isinstance(lines_in, list) or not lines_in:
        raise ValueError("Add at least one asphalt line item")

    shift_type = (payload.get("shift_type") or "day").strip().lower()
    rate_tier = (payload.get("rate_tier") or "").strip().lower()
    if not rate_tier:
        rate_tier = "night" if shift_type == "night" else "weekday"

    lines_out: list[dict[str, Any]] = []
    subtotal = 0.0
    for raw in lines_in:
        if not isinstance(raw, dict):
            continue
        qty = float(raw.get("quantity") or 0)
        if qty < 0:
            raise ValueError("Quantities cannot be negative")
        unit_rate = pick_tier_rate(raw, rate_tier)
        # Explicit unit_rate wins when provided
        if raw.get("unit_rate") is not None and raw.get("unit_rate") != "":
            unit_rate = float(raw["unit_rate"])
        line_total = round(qty * unit_rate, 2)
        subtotal += line_total
        lines_out.append(
            {
                "rate_id": raw.get("rate_id"),
                "name": (raw.get("name") or "Line").strip() or "Line",
                "unit": (raw.get("unit") or "m2").strip() or "m2",
                "quantity": qty,
                "unit_rate": unit_rate,
                "rate_tier": rate_tier,
                "line_total": line_total,
            }
        )

    if not lines_out:
        raise ValueError("Add at least one asphalt line item")

    contingency_pct = float(payload.get("contingency_pct") or 0)
    contingency = round(subtotal * contingency_pct / 100.0, 2) if contingency_pct else 0.0
    total = round(subtotal + contingency, 2)

    return {
        "lines": lines_out,
        "subtotal": round(subtotal, 2),
        "contingency_pct": contingency_pct,
        "contingency": contingency,
        "total": total,
        "rate_tier": rate_tier,
        "shift_type": shift_type,
        "subcontractor_id": payload.get("subcontractor_id"),
        "subcontractor_name": payload.get("subcontractor_name"),
    }
