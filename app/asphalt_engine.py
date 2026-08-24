"""Asphalt cost calculation, rate typing, and subcontractor comparison."""

from __future__ import annotations

from typing import Any

UNIT_UNITS = {"m2", "m²", "msq", "sqm", "sq.m", "sqmetre", "tonne", "t", "lm", "m", "lump", "each", "ea", "item"}
SHIFT_UNITS = {"shift", "day", "crew", "mobilisation", "mobilization", "mob", "establishment"}
SHIFT_NAME_HINTS = ("mobilis", "mobiliz", "crew", "establishment", "set up", "setup", "standby")


def normalize_unit(unit: str | None) -> str:
    raw = (unit or "m2").strip().lower().replace("²", "2").replace(" ", "")
    aliases = {
        "m2": "m2",
        "msq": "m2",
        "sqm": "m2",
        "sq.m": "m2",
        "sqmetre": "m2",
        "sqmeter": "m2",
        "tonne": "tonne",
        "tonnes": "tonne",
        "t": "tonne",
        "lm": "lm",
        "linm": "lm",
        "m": "lm",
        "shift": "shift",
        "day": "day",
        "crew": "shift",
        "mobilisation": "shift",
        "mobilization": "shift",
        "mob": "shift",
        "lump": "lump",
        "ls": "lump",
        "each": "each",
        "ea": "each",
        "item": "each",
    }
    return aliases.get(raw, raw or "m2")


def infer_rate_type(unit: str | None, name: str | None = None) -> str:
    """unit = single $/qty rate; shift = day/night/weekend/PH."""
    n = (name or "").strip().lower()
    if any(h in n for h in SHIFT_NAME_HINTS):
        return "shift"
    u = normalize_unit(unit)
    if u in SHIFT_UNITS or u in ("shift", "day"):
        return "shift"
    return "unit"


def weekend_rate(rate_row: dict[str, Any]) -> float:
    """Sunday is the source of truth; Saturday copies it when unset."""
    sunday = float(rate_row.get("sunday_rate") or 0)
    saturday = float(rate_row.get("saturday_rate") or 0)
    return sunday or saturday


def pick_tier_rate(rate_row: dict[str, Any], tier: str) -> float:
    """Return the unit rate for a calendar tier, falling back sensibly.

    Weekend (Sat+Sun) uses the Sunday / weekend rate. Unit-type items typically
    store the same figure on every column so any tier returns the unit rate.
    """
    day = float(rate_row.get("day_rate") or 0)
    night = float(rate_row.get("night_rate") or 0) or day
    weekend = weekend_rate(rate_row) or night or day
    ph = float(rate_row.get("public_holiday_rate") or 0) or weekend
    t = (tier or "weekday").strip().lower()
    if t in ("public_holiday", "ph", "holiday"):
        return ph
    if t in ("weekend", "saturday", "sunday", "sat", "sun"):
        return weekend
    if t == "night":
        return night
    return day


def apply_stored_rates(payload: dict[str, Any], *, rate_type: str) -> dict[str, Any]:
    """Normalise stored tier columns for unit vs shift items."""
    out = dict(payload)
    if rate_type == "unit":
        unit_rate = float(
            out.get("unit_rate")
            if out.get("unit_rate") not in (None, "")
            else out.get("day_rate") or 0
        )
        out["day_rate"] = unit_rate
        out["night_rate"] = unit_rate
        out["saturday_rate"] = unit_rate
        out["sunday_rate"] = unit_rate
        out["public_holiday_rate"] = unit_rate
    else:
        weekend = weekend_rate(out)
        if weekend:
            out["saturday_rate"] = weekend
            out["sunday_rate"] = weekend
    return out


def calculate_asphalt(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate asphalt line totals.

    Expected payload keys:
      - shift_type: day|night (default day)
      - rate_tier: weekday|night|weekend|public_holiday (optional override)
      - lines: [{ rate_id?, name, unit, rate_type?, quantity, day_rate, ... }]
    """
    lines_in = payload.get("lines") or []
    if not isinstance(lines_in, list) or not lines_in:
        raise ValueError("Add at least one asphalt line item")

    shift_type = (payload.get("shift_type") or "day").strip().lower()
    rate_tier = (payload.get("rate_tier") or "").strip().lower()
    if not rate_tier:
        rate_tier = "night" if shift_type == "night" else "weekday"
    if rate_tier in ("saturday", "sunday"):
        rate_tier = "weekend"

    lines_out: list[dict[str, Any]] = []
    subtotal = 0.0
    for raw in lines_in:
        if not isinstance(raw, dict):
            continue
        qty = float(raw.get("quantity") or 0)
        if qty < 0:
            raise ValueError("Quantities cannot be negative")
        rate_type = (raw.get("rate_type") or infer_rate_type(raw.get("unit"), raw.get("name"))).strip().lower()
        stored = apply_stored_rates(raw, rate_type=rate_type)
        unit_rate = pick_tier_rate(stored, rate_tier)
        if raw.get("unit_rate") not in (None, "") and rate_type == "unit":
            unit_rate = float(raw["unit_rate"])
        line_total = round(qty * unit_rate, 2)
        subtotal += line_total
        lines_out.append(
            {
                "rate_id": raw.get("rate_id"),
                "name": (raw.get("name") or "Line").strip() or "Line",
                "unit": normalize_unit(raw.get("unit")),
                "rate_type": rate_type,
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


def _norm_name(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def match_rate_for_line(line: dict[str, Any], rates: list[dict[str, Any]]) -> dict[str, Any] | None:
    rate_id = line.get("rate_id")
    if rate_id:
        for r in rates:
            if r.get("id") == rate_id:
                return r
    want = _norm_name(line.get("name") or line.get("treatment"))
    if not want:
        return None
    exact = [r for r in rates if _norm_name(r.get("name")) == want]
    if exact:
        return exact[0]
    return None


def compare_subcontractors(
    *,
    lines: list[dict[str, Any]],
    subcontractors: list[dict[str, Any]],
    rates: list[dict[str, Any]],
    shift_type: str = "day",
    rate_tier: str | None = None,
    contingency_pct: float = 0,
) -> dict[str, Any]:
    """Price the same treatment quantities against every subcontractor.

    Returns per-sub totals plus a mixed-best package (cheapest sub per line).
    """
    if not lines:
        raise ValueError("Add at least one asphalt line item")
    active_subs = [s for s in subcontractors if s.get("active", True)]
    by_sub: dict[Any, list[dict[str, Any]]] = {}
    for r in rates:
        if not r.get("active", True):
            continue
        by_sub.setdefault(r.get("subcontractor_id"), []).append(r)

    packages: list[dict[str, Any]] = []
    mixed_lines: list[dict[str, Any]] = []

    for line in lines:
        if not isinstance(line, dict):
            continue
        qty = float(line.get("quantity") or 0)
        name = (line.get("name") or line.get("treatment") or "Line").strip() or "Line"
        unit = normalize_unit(line.get("unit"))
        candidates: list[dict[str, Any]] = []
        for sub in active_subs:
            sub_rates = by_sub.get(sub["id"], [])
            matched = match_rate_for_line({**line, "name": name}, sub_rates)
            if not matched:
                continue
            calc = calculate_asphalt(
                {
                    "shift_type": shift_type,
                    "rate_tier": rate_tier,
                    "contingency_pct": 0,
                    "lines": [{**matched, "quantity": qty, "name": name, "unit": matched.get("unit") or unit}],
                    "subcontractor_id": sub["id"],
                    "subcontractor_name": sub.get("name"),
                }
            )
            priced = calc["lines"][0]
            candidates.append(
                {
                    "subcontractor_id": sub["id"],
                    "subcontractor_name": sub.get("name"),
                    "rate_id": matched.get("id"),
                    "unit_rate": priced["unit_rate"],
                    "line_total": priced["line_total"],
                    "unit": priced["unit"],
                    "rate_type": priced["rate_type"],
                }
            )
        best = min(candidates, key=lambda c: c["line_total"]) if candidates else None
        mixed_lines.append(
            {
                "name": name,
                "unit": unit,
                "quantity": qty,
                "quotes": candidates,
                "best": best,
                "missing": [s["name"] for s in active_subs if s["id"] not in {c["subcontractor_id"] for c in candidates}],
            }
        )

    for sub in active_subs:
        line_rows: list[dict[str, Any]] = []
        missing: list[str] = []
        subtotal = 0.0
        for item in mixed_lines:
            quote = next((q for q in item["quotes"] if q["subcontractor_id"] == sub["id"]), None)
            if quote is None:
                missing.append(item["name"])
                continue
            line_rows.append({**quote, "name": item["name"], "quantity": item["quantity"]})
            subtotal += quote["line_total"]
        contingency = round(subtotal * float(contingency_pct or 0) / 100.0, 2) if contingency_pct else 0.0
        packages.append(
            {
                "subcontractor_id": sub["id"],
                "subcontractor_name": sub.get("name"),
                "lines": line_rows,
                "missing": missing,
                "complete": not missing,
                "subtotal": round(subtotal, 2),
                "contingency": contingency,
                "total": round(subtotal + contingency, 2),
            }
        )

    complete = [p for p in packages if p["complete"]]
    best_package = min(complete, key=lambda p: p["total"]) if complete else (
        min(packages, key=lambda p: p["total"]) if packages else None
    )
    for p in packages:
        p["best"] = bool(best_package and p["subcontractor_id"] == best_package["subcontractor_id"])

    mixed_subtotal = round(sum((m["best"] or {}).get("line_total") or 0 for m in mixed_lines), 2)
    mixed_contingency = round(mixed_subtotal * float(contingency_pct or 0) / 100.0, 2) if contingency_pct else 0.0
    return {
        "shift_type": shift_type,
        "rate_tier": (rate_tier or ("night" if shift_type == "night" else "weekday")),
        "contingency_pct": float(contingency_pct or 0),
        "packages": packages,
        "best_subcontractor_id": best_package["subcontractor_id"] if best_package else None,
        "best_subcontractor_name": best_package["subcontractor_name"] if best_package else None,
        "best_total": best_package["total"] if best_package else None,
        "mixed_best": {
            "lines": mixed_lines,
            "subtotal": mixed_subtotal,
            "contingency": mixed_contingency,
            "total": round(mixed_subtotal + mixed_contingency, 2),
        },
    }


def rate_card_matrix(
    *,
    subcontractors: list[dict[str, Any]],
    rates: list[dict[str, Any]],
    rate_tier: str = "weekday",
) -> dict[str, Any]:
    """Pivot treatments (shared names) × subcontractors for a rate-card comparison."""
    active_subs = [s for s in subcontractors if s.get("active", True)]
    treatments: dict[str, dict[str, Any]] = {}
    for r in rates:
        if not r.get("active", True):
            continue
        key = _norm_name(r.get("name"))
        if not key:
            continue
        bucket = treatments.setdefault(
            key,
            {
                "name": (r.get("name") or "").strip(),
                "unit": normalize_unit(r.get("unit")),
                "rate_type": r.get("rate_type") or infer_rate_type(r.get("unit"), r.get("name")),
                "cells": {},
            },
        )
        priced = pick_tier_rate(r, rate_tier)
        if bucket["rate_type"] == "unit":
            priced = float(r.get("day_rate") or priced)
        sid = r.get("subcontractor_id")
        existing = bucket["cells"].get(sid)
        if existing is None or priced < existing["unit_rate"]:
            bucket["cells"][sid] = {
                "rate_id": r.get("id"),
                "unit_rate": priced,
                "day_rate": float(r.get("day_rate") or 0),
                "night_rate": float(r.get("night_rate") or 0),
                "weekend_rate": weekend_rate(r),
                "public_holiday_rate": float(r.get("public_holiday_rate") or 0),
            }

    rows = []
    for bucket in sorted(treatments.values(), key=lambda b: b["name"].lower()):
        values = [c["unit_rate"] for c in bucket["cells"].values()]
        best = min(values) if values else None
        cells = []
        for sub in active_subs:
            cell = bucket["cells"].get(sub["id"])
            cells.append(
                {
                    "subcontractor_id": sub["id"],
                    "subcontractor_name": sub.get("name"),
                    "unit_rate": cell["unit_rate"] if cell else None,
                    "best": bool(cell and best is not None and cell["unit_rate"] == best),
                    "missing": cell is None,
                    **({k: cell[k] for k in ("rate_id", "day_rate", "night_rate", "weekend_rate", "public_holiday_rate")} if cell else {}),
                }
            )
        rows.append(
            {
                "name": bucket["name"],
                "unit": bucket["unit"],
                "rate_type": bucket["rate_type"],
                "best_rate": best,
                "cells": cells,
            }
        )
    return {
        "rate_tier": rate_tier,
        "subcontractors": [{"id": s["id"], "name": s.get("name")} for s in active_subs],
        "treatments": rows,
    }
