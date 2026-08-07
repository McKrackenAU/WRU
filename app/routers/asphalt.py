"""Asphalt subcontractors, rates, and estimates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..asphalt_engine import calculate_asphalt
from ..auth import require_admin
from ..database import get_db
from ..models import AsphaltEstimate, AsphaltRate, AsphaltSubcontractor, Site, User

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
    day_rate: float = 0
    night_rate: float = 0
    saturday_rate: float = 0
    sunday_rate: float = 0
    public_holiday_rate: float = 0
    active: bool = True
    position: int | None = None


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subcontractor_id: int
    name: str
    unit: str
    day_rate: float
    night_rate: float
    saturday_rate: float
    sunday_rate: float
    public_holiday_rate: float
    active: bool
    position: int


class CalculateIn(BaseModel):
    subcontractor_id: int | None = None
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


@router.get("/rates", response_model=list[RateOut])
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
    return q.order_by(AsphaltRate.position.asc(), AsphaltRate.id.asc()).all()


@router.post("/rates", response_model=RateOut, status_code=201)
def create_rate(
    payload: RateIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(AsphaltSubcontractor, payload.subcontractor_id):
        raise HTTPException(status_code=404, detail="Subcontractor not found")
    max_pos = db.query(func.max(AsphaltRate.position)).scalar() or 0
    row = AsphaltRate(
        subcontractor_id=payload.subcontractor_id,
        name=payload.name.strip(),
        unit=(payload.unit or "m2").strip() or "m2",
        day_rate=payload.day_rate,
        night_rate=payload.night_rate,
        saturday_rate=payload.saturday_rate,
        sunday_rate=payload.sunday_rate,
        public_holiday_rate=payload.public_holiday_rate,
        active=payload.active,
        position=payload.position if payload.position is not None else max_pos + 1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/rates/{rate_id}", response_model=RateOut)
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
    row.subcontractor_id = payload.subcontractor_id
    row.name = payload.name.strip()
    row.unit = (payload.unit or "m2").strip() or "m2"
    row.day_rate = payload.day_rate
    row.night_rate = payload.night_rate
    row.saturday_rate = payload.saturday_rate
    row.sunday_rate = payload.sunday_rate
    row.public_holiday_rate = payload.public_holiday_rate
    row.active = payload.active
    if payload.position is not None:
        row.position = payload.position
    db.commit()
    db.refresh(row)
    return row


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


@router.get("/estimates")
def list_estimates(site_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(AsphaltEstimate)
    if site_id:
        q = q.filter(AsphaltEstimate.site_id == site_id)
    rows = q.order_by(AsphaltEstimate.created_at.desc()).limit(200).all()
    return [_estimate_out(r) for r in rows]


@router.post("/estimates", status_code=201)
def save_estimate(payload: EstimateSave, db: Session = Depends(get_db)):
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
