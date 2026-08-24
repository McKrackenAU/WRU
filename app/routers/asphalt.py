"""Asphalt subcontractors, rates, and estimates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..asphalt_engine import (
    apply_stored_rates,
    calculate_asphalt,
    compare_subcontractors,
    infer_rate_type,
    normalize_unit,
    rate_card_matrix,
    weekend_rate,
)
from ..auth import require_admin
from ..database import get_db
from ..models import AsphaltEstimate, AsphaltRate, AsphaltSubcontractor, Site, User
from ..rate_import import build_asphalt_template, import_asphalt_rates

router = APIRouter(prefix="/api/asphalt", tags=["asphalt"])


class SubcontractorIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    notes: str | None = None
    work_weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    rdo_dates: list[str] = Field(default_factory=list)
    skip_public_holidays: bool = True
    skip_sunday_before_monday_ph: bool = True
    active: bool = True
    position: int | None = None


class SubcontractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    notes: str | None = None
    work_weekdays: list
    rdo_dates: list
    skip_public_holidays: bool
    skip_sunday_before_monday_ph: bool
    active: bool
    position: int


class RateIn(BaseModel):
    subcontractor_id: int
    name: str = Field(min_length=1, max_length=128)
    unit: str = Field(default="m2", max_length=32)
    rate_type: str | None = None
    unit_rate: float | None = None
    day_rate: float = 0
    night_rate: float = 0
    saturday_rate: float = 0
    sunday_rate: float = 0
    weekend_rate: float | None = None
    public_holiday_rate: float = 0
    active: bool = True
    position: int | None = None


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subcontractor_id: int
    name: str
    unit: str
    rate_type: str
    day_rate: float
    night_rate: float
    saturday_rate: float
    sunday_rate: float
    weekend_rate: float
    public_holiday_rate: float
    active: bool
    position: int


class CalculateIn(BaseModel):
    subcontractor_id: int | None = None
    shift_type: str = "day"
    rate_tier: str | None = None
    contingency_pct: float = 0
    lines: list[dict] = Field(default_factory=list)


class CompareIn(BaseModel):
    shift_type: str = "day"
    rate_tier: str | None = None
    contingency_pct: float = 0
    lines: list[dict] = Field(default_factory=list)


class EstimateSave(BaseModel):
    site_id: int
    subcontractor_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    notes: str | None = None
    inputs: dict = Field(default_factory=dict)
    results: dict = Field(default_factory=dict)
    summary_total: float | None = None
    created_by: str | None = None


class EstimateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    subcontractor_id: int | None = None
    name: str
    notes: str | None = None
    summary_total: float | None = None
    inputs: dict
    results: dict
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _rate_public(row: AsphaltRate) -> dict:
    data = {
        "id": row.id,
        "subcontractor_id": row.subcontractor_id,
        "name": row.name,
        "unit": row.unit,
        "rate_type": getattr(row, "rate_type", None) or infer_rate_type(row.unit, row.name),
        "day_rate": float(row.day_rate or 0),
        "night_rate": float(row.night_rate or 0),
        "saturday_rate": float(row.saturday_rate or 0),
        "sunday_rate": float(row.sunday_rate or 0),
        "public_holiday_rate": float(row.public_holiday_rate or 0),
        "active": row.active,
        "position": row.position,
    }
    data["weekend_rate"] = weekend_rate(data)
    return data


def _apply_rate_payload(row: AsphaltRate, payload: RateIn) -> None:
    unit = normalize_unit(payload.unit)
    name = payload.name.strip()
    rate_type = (payload.rate_type or infer_rate_type(unit, name)).strip().lower()
    if rate_type not in ("unit", "shift"):
        rate_type = infer_rate_type(unit, name)
    weekend = payload.weekend_rate
    if weekend is None:
        weekend = payload.sunday_rate or payload.saturday_rate
    stored = apply_stored_rates(
        {
            "unit_rate": payload.unit_rate,
            "day_rate": payload.day_rate,
            "night_rate": payload.night_rate,
            "saturday_rate": payload.saturday_rate,
            "sunday_rate": payload.sunday_rate or weekend or 0,
            "public_holiday_rate": payload.public_holiday_rate,
        },
        rate_type=rate_type,
    )
    row.subcontractor_id = payload.subcontractor_id
    row.name = name
    row.unit = unit
    row.rate_type = rate_type
    row.day_rate = stored["day_rate"]
    row.night_rate = stored["night_rate"]
    row.saturday_rate = stored["saturday_rate"]
    row.sunday_rate = stored["sunday_rate"]
    row.public_holiday_rate = stored["public_holiday_rate"]
    row.active = payload.active
    if payload.position is not None:
        row.position = payload.position


def _estimate_out(row: AsphaltEstimate) -> dict:
    return {
        "id": row.id,
        "site_id": row.site_id,
        "subcontractor_id": row.subcontractor_id,
        "name": row.name,
        "notes": row.notes,
        "summary_total": row.summary_total,
        "inputs": row.inputs or {},
        "results": row.results or {},
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/subcontractors", response_model=list[SubcontractorOut])
def list_subcontractors(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(AsphaltSubcontractor)
    if active_only:
        q = q.filter(AsphaltSubcontractor.active.is_(True))
    return q.order_by(AsphaltSubcontractor.position.asc(), AsphaltSubcontractor.name.asc()).all()


@router.post("/subcontractors", response_model=SubcontractorOut, status_code=201)
def create_subcontractor(
    payload: SubcontractorIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    name = payload.name.strip()
    if db.query(AsphaltSubcontractor).filter(func.lower(AsphaltSubcontractor.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="Subcontractor already exists")
    max_pos = db.query(func.max(AsphaltSubcontractor.position)).scalar() or 0
    row = AsphaltSubcontractor(
        name=name,
        notes=payload.notes,
        work_weekdays=payload.work_weekdays or [0, 1, 2, 3, 4],
        rdo_dates=payload.rdo_dates or [],
        skip_public_holidays=payload.skip_public_holidays,
        skip_sunday_before_monday_ph=payload.skip_sunday_before_monday_ph,
        active=payload.active,
        position=payload.position if payload.position is not None else max_pos + 1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/subcontractors/{sub_id}", response_model=SubcontractorOut)
def update_subcontractor(
    sub_id: int,
    payload: SubcontractorIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(AsphaltSubcontractor, sub_id)
    if not row:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    name = payload.name.strip()
    clash = (
        db.query(AsphaltSubcontractor)
        .filter(func.lower(AsphaltSubcontractor.name) == name.lower(), AsphaltSubcontractor.id != sub_id)
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="Subcontractor already exists")
    row.name = name
    row.notes = payload.notes
    row.work_weekdays = payload.work_weekdays or [0, 1, 2, 3, 4]
    row.rdo_dates = payload.rdo_dates or []
    row.skip_public_holidays = payload.skip_public_holidays
    row.skip_sunday_before_monday_ph = payload.skip_sunday_before_monday_ph
    row.active = payload.active
    if payload.position is not None:
        row.position = payload.position
    db.commit()
    db.refresh(row)
    return row


@router.delete("/subcontractors/{sub_id}", status_code=204)
def delete_subcontractor(
    sub_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(AsphaltSubcontractor, sub_id)
    if not row:
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    db.delete(row)
    db.commit()
    return None


@router.get("/rates")
def list_rates(
    subcontractor_id: int | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(AsphaltRate)
    if subcontractor_id:
        q = q.filter(AsphaltRate.subcontractor_id == subcontractor_id)
    if active_only:
        q = q.filter(AsphaltRate.active.is_(True))
    rows = q.order_by(AsphaltRate.position.asc(), AsphaltRate.id.asc()).all()
    return [_rate_public(r) for r in rows]


@router.post("/rates", status_code=201)
def create_rate(
    payload: RateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(AsphaltSubcontractor, payload.subcontractor_id):
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    max_pos = db.query(func.max(AsphaltRate.position)).scalar() or 0
    row = AsphaltRate(position=payload.position if payload.position is not None else max_pos + 1)
    _apply_rate_payload(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _rate_public(row)


@router.patch("/rates/{rate_id}")
def update_rate(
    rate_id: int,
    payload: RateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(AsphaltRate, rate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    if not db.get(AsphaltSubcontractor, payload.subcontractor_id):
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    _apply_rate_payload(row, payload)
    db.commit()
    db.refresh(row)
    return _rate_public(row)


@router.delete("/rates/{rate_id}", status_code=204)
def delete_rate(
    rate_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(AsphaltRate, rate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    db.delete(row)
    db.commit()
    return None


@router.post("/calculate")
def calculate(payload: CalculateIn, db: Session = Depends(get_db)):
    data = payload.model_dump()
    if payload.subcontractor_id:
        sub = db.get(AsphaltSubcontractor, payload.subcontractor_id)
        if sub:
            data["subcontractor_name"] = sub.name
    try:
        return calculate_asphalt(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compare")
def compare_asphalt(payload: CompareIn, db: Session = Depends(get_db)):
    subs = [
        {"id": s.id, "name": s.name, "active": s.active}
        for s in db.query(AsphaltSubcontractor).order_by(AsphaltSubcontractor.position, AsphaltSubcontractor.name)
    ]
    rates = [_rate_public(r) for r in db.query(AsphaltRate).all()]
    try:
        return compare_subcontractors(
            lines=payload.lines,
            subcontractors=subs,
            rates=rates,
            shift_type=payload.shift_type,
            rate_tier=payload.rate_tier,
            contingency_pct=payload.contingency_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rates/matrix")
def get_rate_matrix(
    rate_tier: str = Query(default="weekday"),
    db: Session = Depends(get_db),
):
    subs = [
        {"id": s.id, "name": s.name, "active": s.active}
        for s in db.query(AsphaltSubcontractor).order_by(AsphaltSubcontractor.position, AsphaltSubcontractor.name)
    ]
    rates = [_rate_public(r) for r in db.query(AsphaltRate).all()]
    return rate_card_matrix(subcontractors=subs, rates=rates, rate_tier=rate_tier)


@router.get("/rates/template.xlsx")
def download_asphalt_template(_: User = Depends(require_admin)):
    data = build_asphalt_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="asphalt-rates-template.xlsx"'},
    )


@router.post("/rates/import")
async def import_asphalt_rate_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Upload a .csv or .xlsx rate card")
    content = await file.read()
    try:
        return import_asphalt_rates(db, content, file.filename or "rates.xlsx")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/estimates")
def list_estimates(site_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(AsphaltEstimate)
    if site_id:
        q = q.filter(AsphaltEstimate.site_id == site_id)
    rows = q.order_by(AsphaltEstimate.created_at.desc()).limit(200).all()
    return [_estimate_out(r) for r in rows]


@router.post("/estimates", status_code=201)
def save_estimate(payload: EstimateSave, db: Session = Depends(get_db)):
    from ..spend_from_estimates import upsert_spend_from_estimate

    site = db.get(Site, payload.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if payload.subcontractor_id and not db.get(AsphaltSubcontractor, payload.subcontractor_id):
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    total = payload.summary_total
    if total is None:
        total = (payload.results or {}).get("total")
    row = AsphaltEstimate(
        site_id=payload.site_id,
        subcontractor_id=payload.subcontractor_id,
        name=payload.name.strip(),
        notes=payload.notes,
        summary_total=total,
        inputs=payload.inputs or {},
        results=payload.results or {},
        created_by=payload.created_by,
    )
    db.add(row)
    db.flush()
    upsert_spend_from_estimate(
        db,
        kind="asphalt",
        site_id=payload.site_id,
        amount=float(total) if total is not None else None,
        estimate_id=row.id,
        estimate_name=row.name,
        asphalt_subcontractor_id=payload.subcontractor_id,
        created_by=payload.created_by,
    )
    db.commit()
    db.refresh(row)
    return _estimate_out(row)


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: int, db: Session = Depends(get_db)):
    row = db.get(AsphaltEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")
    db.delete(row)
    db.commit()
    return None
