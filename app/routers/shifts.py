from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import ShiftReport, Site, User
from ..shift_export import build_shift_report_pdf, pdf_filename
from ..weather import fetch_weather

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


class ShiftIn(BaseModel):
    site_id: int
    work_date: date
    shift_type: str = Field(default="day", pattern="^(day|night)$")
    crew: str | None = None
    notes: str | None = None
    works_done: str | None = None
    issues: str | None = None
    lat: float | None = None
    lng: float | None = None
    weather: dict | None = None
    details: dict | None = None
    polygons: list | None = None


class ShiftPatch(BaseModel):
    work_date: date | None = None
    shift_type: str | None = Field(default=None, pattern="^(day|night)$")
    crew: str | None = None
    notes: str | None = None
    works_done: str | None = None
    issues: str | None = None
    weather: dict | None = None
    append_weather: dict | None = None
    details: dict | None = None
    polygons: list | None = None


def _public(row: ShiftReport) -> dict:
    site = row.site
    return {
        "id": row.id,
        "site_id": row.site_id,
        "road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
        "archived": bool(site.archived) if site else False,
        "work_date": row.work_date.isoformat() if row.work_date else None,
        "shift_type": row.shift_type,
        "crew": row.crew,
        "weather": row.weather or {},
        "weather_log": row.weather_log or [],
        "notes": row.notes,
        "works_done": row.works_done,
        "issues": row.issues,
        "lat": row.lat,
        "lng": row.lng,
        "details": row.details or {},
        "polygons": row.polygons or [],
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_shifts(
    site_id: int | None = None,
    include_archived: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(ShiftReport)
    if site_id:
        q = q.filter(ShiftReport.site_id == site_id)
    elif not include_archived:
        q = q.join(Site).filter(Site.archived.is_(False))
    rows = q.order_by(ShiftReport.work_date.desc(), ShiftReport.id.desc()).limit(200).all()
    return [_public(r) for r in rows]


@router.post("", status_code=201)
def create_shift(
    payload: ShiftIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    site = db.get(Site, payload.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    weather = payload.weather or {}
    if payload.lat is not None and payload.lng is not None and not weather:
        try:
            weather = fetch_weather(payload.lat, payload.lng)
        except Exception:
            weather = {}
    row = ShiftReport(
        site_id=site.id,
        work_date=payload.work_date,
        shift_type=payload.shift_type,
        crew=(payload.crew or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        works_done=(payload.works_done or "").strip() or None,
        issues=(payload.issues or "").strip() or None,
        weather=weather,
        weather_log=[weather] if weather else [],
        lat=payload.lat,
        lng=payload.lng,
        details=payload.details or {},
        polygons=payload.polygons or [],
        created_by=user.display_name or user.username,
    )
    db.add(row)
    db.flush()
    from ..lot_register import sync_lot

    sync_lot(db, row)
    db.commit()
    db.refresh(row)
    return _public(row)


@router.patch("/{shift_id}")
def update_shift(
    shift_id: int,
    payload: ShiftPatch,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ShiftReport, shift_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shift report not found")
    data = payload.model_dump(exclude_unset=True)
    extra = data.pop("append_weather", None)
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    if extra:
        log = list(row.weather_log or [])
        log.append(extra)
        row.weather_log = log
        row.weather = extra
    from ..lot_register import sync_lot

    sync_lot(db, row)
    db.commit()
    db.refresh(row)
    return _public(row)


@router.post("/{shift_id}/actual-spend")
def post_actual_spend(
    shift_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..shift_costs import post_shift_spend

    row = db.get(ShiftReport, shift_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shift report not found")
    result = post_shift_spend(db, row, created_by=user.display_name or user.username)
    result["shift"] = _public(row)
    return result


@router.get("/{shift_id}/export.pdf")
def export_shift_pdf(
    shift_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ShiftReport, shift_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shift report not found")
    site = {
        "road_name": row.site.road_name if row.site else "",
        "site_number": row.site.site_number if row.site else "",
    }
    public = _public(row)
    pdf = build_shift_report_pdf(public, site)
    filename = pdf_filename(public, site)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{shift_id}/refresh-weather")
def refresh_weather(
    shift_id: int,
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(ShiftReport, shift_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shift report not found")
    use_lat = lat if lat is not None else row.lat
    use_lng = lng if lng is not None else row.lng
    if use_lat is None or use_lng is None:
        raise HTTPException(status_code=400, detail="Need a map location for weather")
    try:
        snap = fetch_weather(use_lat, use_lng)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log = list(row.weather_log or [])
    prev = (row.weather or {}).get("label")
    if prev and prev != snap.get("label"):
        log.append(snap)
    elif not log:
        log.append(snap)
    else:
        log[-1] = snap
    row.weather = snap
    row.weather_log = log
    row.lat = use_lat
    row.lng = use_lng
    db.commit()
    db.refresh(row)
    return _public(row)
