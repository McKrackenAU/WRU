"""Keep a lot register row in step with each shift report."""

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .lot_numbers import build_lot_number, compact_fmrp, road_number_from_name, work_kind_code
from .models import LotRegister, ShiftReport


def lot_for_shift(report: ShiftReport) -> str:
    details = report.details or {}
    explicit = str(details.get("lot_number") or "").strip()
    site = report.site
    road_name = site.road_name if site else ""
    site_number = site.site_number if site else ""
    built = build_lot_number(
        work_date=report.work_date.isoformat() if report.work_date else "",
        road_number=details.get("road_number") or road_number_from_name(road_name),
        fmrp_year=details.get("fmrp_year"),
        site_number=site_number,
        work_kind=details.get("work_kind"),
        mix=details.get("asphalt_type"),
        supervisor=details.get("supervisor") or report.crew,
    )
    return explicit or built


def _unique_lot(db: Session, lot: str, shift_id: int) -> str:
    base = lot or f"shift-{shift_id}"
    candidate = base
    suffix = 2
    while True:
        clash = (
            db.query(LotRegister)
            .filter(LotRegister.lot_number == candidate, LotRegister.shift_id != shift_id)
            .first()
        )
        if clash is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def sync_lot(db: Session, report: ShiftReport) -> LotRegister:
    """Create or update the register row for this shift. Caller commits."""
    details = dict(report.details or {})
    lot = _unique_lot(db, lot_for_shift(report), report.id)
    if details.get("lot_number") != lot:
        details["lot_number"] = lot
        report.details = details
        flag_modified(report, "details")
    site = report.site
    row = db.query(LotRegister).filter(LotRegister.shift_id == report.id).one_or_none()
    if row is None:
        row = LotRegister(shift_id=report.id, site_id=report.site_id, lot_number=lot)
        db.add(row)
    row.lot_number = lot
    row.site_id = report.site_id
    row.work_date = report.work_date
    row.road_name = site.road_name if site else None
    row.road_number = str(details.get("road_number") or road_number_from_name(row.road_name or "") or "") or None
    row.fmrp_year = compact_fmrp(details.get("fmrp_year")) or None
    row.site_number = site.site_number if site else None
    row.work_kind = "pro" if work_kind_code(details.get("work_kind")) == "PRO" else "hma"
    row.mix = None if row.work_kind == "pro" else (str(details.get("asphalt_type") or "").strip() or None)
    row.supervisor = str(details.get("supervisor") or report.crew or "").strip() or None
    return row
