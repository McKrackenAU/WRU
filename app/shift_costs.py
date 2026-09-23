"""Turn a lifecycle shift report into traffic and asphalt actual spend."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .asphalt_engine import calculate_asphalt, pick_area_band_rate, pick_tier_rate
from .cost_engine import resolve_shift_labour
from .models import ActualSpend, AsphaltRate, AsphaltSubcontractor, CostSettings, LabourRate, ShiftReport


def hours_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None

    def parse(raw: str) -> datetime:
        text = str(raw).strip().replace("Z", "")
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(text)

    try:
        opened = parse(start)
        closed = parse(end)
    except (TypeError, ValueError):
        return None
    if closed < opened:
        closed += timedelta(days=1)
    return round((closed - opened).total_seconds() / 3600.0, 2)


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _upsert(db: Session, site_id: int, shift_id: int, kind: str, **fields) -> ActualSpend:
    rows = db.query(ActualSpend).filter(ActualSpend.site_id == site_id, ActualSpend.kind == kind).all()
    row = next((item for item in rows if int((item.inputs or {}).get("shift_id") or 0) == shift_id), None)
    if row is None:
        row = ActualSpend(site_id=site_id, kind=kind, inputs={"shift_id": shift_id})
        db.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    inputs = dict(row.inputs or {})
    inputs["shift_id"] = shift_id
    row.inputs = inputs
    return row


def post_shift_spend(db: Session, report: ShiftReport, *, created_by: str | None = None) -> dict[str, Any]:
    details = report.details or {}
    warnings: list[str] = []
    posted: dict[str, Any] = {}
    settings = db.get(CostSettings, 1)
    overtime_after = float(getattr(settings, "overtime_after_hours", 8) or 8)
    tier = "night" if (report.shift_type or "day") == "night" else "weekday"

    hours = hours_between(details.get("traffic_crew_start"), details.get("traffic_crew_end"))
    people = _int(details.get("total_tc"))
    vehicles = _int(details.get("vehicles"))
    tmas = _int(details.get("arrow_boards"))
    spotters = _int(details.get("spotters"))
    if hours and hours > 0 and (people or vehicles or tmas or spotters):
        rates = db.query(LabourRate).filter(LabourRate.active.is_(True)).all()
        try:
            labour = resolve_shift_labour(
                {
                    "people": people,
                    "vehicles": vehicles,
                    "tmas": tmas,
                    "spotters": spotters,
                    "travel_allowance": getattr(settings, "travel_allowance", 0) if settings else 0,
                    "meal_allowance": getattr(settings, "meal_allowance", 0) if settings else 0,
                    "meal_after_hours": getattr(settings, "meal_after_hours", 9.5) if settings else 9.5,
                },
                shift_hours=hours,
                shift_type=report.shift_type or "day",
                overtime_after=overtime_after,
                rates=rates,
                settings=settings,
                rate_tier=tier,
            )
            amount = float(labour.get("shift_total") or 0)
            row = _upsert(
                db,
                report.site_id,
                report.id,
                "traffic",
                work_date=report.work_date,
                amount=amount,
                source="calculated",
                category="shift",
                notes=f"Shift report {report.work_date} · {hours:g}h · {people} TC",
                results=labour,
                created_by=created_by,
            )
            row.inputs = {"shift_id": report.id, "hours": hours, "people": people, "vehicles": vehicles, "tmas": tmas}
            posted["traffic"] = {"amount": amount, "hours": hours, "summary": labour.get("booking_summary")}
        except Exception as exc:
            warnings.append(f"Traffic cost was not posted: {exc}")
    else:
        warnings.append("Traffic cost needs a crew start, crew end, and at least one TC, vehicle, arrow board, or spotter.")

    mix = str(details.get("asphalt_type") or "").strip()
    tonnes = _num(details.get("tonnage"))
    shift_area = _num(details.get("shift_area_m2"))
    site_area = _num(details.get("site_area_m2"))
    thickness = _num(details.get("thickness_mm"))
    unit = "tonne" if tonnes else "m2"
    qty = tonnes if tonnes else shift_area
    if mix and qty:
        rate_rows = db.query(AsphaltRate).filter(AsphaltRate.active.is_(True)).all()
        cards = [
            {
                "id": rate.id,
                "subcontractor_id": rate.subcontractor_id,
                "name": rate.name,
                "unit": rate.unit,
                "rate_type": rate.rate_type,
                "day_rate": rate.day_rate,
                "night_rate": rate.night_rate,
                "saturday_rate": rate.saturday_rate,
                "sunday_rate": rate.sunday_rate,
                "public_holiday_rate": rate.public_holiday_rate,
                "active": rate.active,
                "area_min_m2": rate.area_min_m2,
                "area_max_m2": rate.area_max_m2,
                "thickness_mm": rate.thickness_mm,
            }
            for rate in rate_rows
        ]
        contractor = str(details.get("paving_contractor") or "").strip().lower()
        if contractor:
            subs = {
                row.id: row.name
                for row in db.query(AsphaltSubcontractor).all()
            }
            named = [card for card in cards if contractor in (subs.get(card["subcontractor_id"]) or "").lower()]
            if named:
                cards = named
        chosen = pick_area_band_rate(
            cards,
            mix=mix,
            unit=unit,
            thickness_mm=thickness,
            site_area_m2=site_area,
        )
        if not chosen and unit == "tonne":
            chosen = pick_area_band_rate(
                cards,
                mix=mix,
                unit="m2",
                thickness_mm=thickness,
                site_area_m2=site_area,
            )
            if chosen:
                unit = "m2"
                qty = shift_area
        if not chosen or not qty:
            warnings.append(
                "Asphalt cost was not posted. Add a rate whose name matches the mix, unit (tonne or m²), "
                "thickness, and the site's overall m² band."
            )
        else:
            unit_rate = pick_tier_rate(chosen, tier)
            priced = calculate_asphalt(
                {
                    "shift_type": report.shift_type or "day",
                    "rate_tier": tier,
                    "subcontractor_id": chosen.get("subcontractor_id"),
                    "lines": [
                        {
                            "rate_id": chosen.get("id"),
                            "name": chosen.get("name"),
                            "unit": unit,
                            "rate_type": "unit",
                            "quantity": qty,
                            "day_rate": unit_rate,
                            "night_rate": unit_rate,
                            "unit_rate": unit_rate,
                        }
                    ],
                }
            )
            amount = float(priced["total"])
            band = ""
            if chosen.get("area_min_m2") or chosen.get("area_max_m2"):
                band = f" · band {chosen.get('area_min_m2') or 0:g}–{chosen.get('area_max_m2') or '∞'} m²"
            row = _upsert(
                db,
                report.site_id,
                report.id,
                "asphalt",
                work_date=report.work_date,
                amount=amount,
                source="calculated",
                category="shift",
                asphalt_subcontractor_id=chosen.get("subcontractor_id"),
                notes=(
                    f"Shift report {report.work_date} · {mix} · {qty:g} {unit}"
                    f"{band} · site {site_area:g} m²" if site_area else f"Shift report {report.work_date} · {mix} · {qty:g} {unit}{band}"
                ),
                results=priced,
                created_by=created_by,
            )
            row.inputs = {
                "shift_id": report.id,
                "mix": mix,
                "quantity": qty,
                "unit": unit,
                "site_area_m2": site_area,
                "thickness_mm": thickness,
                "rate_id": chosen.get("id"),
            }
            posted["asphalt"] = {
                "amount": amount,
                "quantity": qty,
                "unit": unit,
                "rate_name": chosen.get("name"),
                "unit_rate": unit_rate,
                "site_area_m2": site_area,
            }
    else:
        warnings.append("Asphalt cost needs a mix and either tonnes or m² laid this shift.")

    db.commit()
    return {"posted": posted, "warnings": warnings}
