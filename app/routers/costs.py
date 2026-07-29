from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..cost_engine import calculate_closure_24h, calculate_standard
from ..database import get_db
from ..models import CostEstimate, CostSettings, LabourRate, Site

router = APIRouter(prefix="/api/costs", tags=["costs"])


class CostSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    overtime_after_hours: float
    vms_lead_days_default: int
    vms_delivery_rate: float
    vms_collection_rate: float
    vms_day_rate: float


class CostSettingsUpdate(BaseModel):
    overtime_after_hours: float | None = Field(default=None, gt=0, le=24)
    vms_lead_days_default: int | None = Field(default=None, ge=0, le=60)
    vms_delivery_rate: float | None = Field(default=None, ge=0)
    vms_collection_rate: float | None = Field(default=None, ge=0)
    vms_day_rate: float | None = Field(default=None, ge=0)


class LabourRateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    day_ordinary: float = Field(ge=0)
    day_overtime: float = Field(ge=0)
    night_ordinary: float = Field(ge=0)
    night_overtime: float = Field(ge=0)
    active: bool = True
    position: int | None = None


class LabourRateOut(LabourRateIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class EstimateSave(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    site_id: int | None = None
    mode: str
    inputs: dict
    results: dict
    created_by: str | None = None


def get_or_create_settings(db: Session) -> CostSettings:
    row = db.get(CostSettings, 1)
    if row:
        return row
    row = CostSettings(
        id=1,
        overtime_after_hours=8.0,
        vms_lead_days_default=7,
        vms_delivery_rate=150.0,
        vms_collection_rate=150.0,
        vms_day_rate=45.0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ensure_default_rates(db: Session) -> None:
    if db.query(LabourRate).count():
        return
    defaults = [
        ("Traffic Controller", 55, 75, 70, 95),
        ("Team Leader", 65, 90, 85, 110),
        ("Supervisor", 80, 110, 100, 135),
        ("Company Vehicle", 25, 25, 35, 35),
    ]
    for idx, (name, d_o, d_ot, n_o, n_ot) in enumerate(defaults, start=1):
        db.add(
            LabourRate(
                name=name,
                day_ordinary=d_o,
                day_overtime=d_ot,
                night_ordinary=n_o,
                night_overtime=n_ot,
                active=True,
                position=idx,
            )
        )
    db.commit()


@router.get("/settings", response_model=CostSettingsOut)
def read_settings(db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    ensure_default_rates(db)
    return s


@router.put("/settings", response_model=CostSettingsOut)
def update_settings(payload: CostSettingsUpdate, db: Session = Depends(get_db)):
    s = get_or_create_settings(db)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.get("/rates", response_model=list[LabourRateOut])
def list_rates(active_only: bool = False, db: Session = Depends(get_db)):
    ensure_default_rates(db)
    q = db.query(LabourRate)
    if active_only:
        q = q.filter(LabourRate.active.is_(True))
    return q.order_by(LabourRate.position.asc(), LabourRate.id.asc()).all()


@router.post("/rates", response_model=LabourRateOut, status_code=201)
def create_rate(payload: LabourRateIn, db: Session = Depends(get_db)):
    if db.query(LabourRate).filter(func.lower(LabourRate.name) == payload.name.strip().lower()).first():
        raise HTTPException(status_code=400, detail="A rate category with this name already exists")
    max_pos = db.query(func.max(LabourRate.position)).scalar() or 0
    row = LabourRate(
        name=payload.name.strip(),
        day_ordinary=payload.day_ordinary,
        day_overtime=payload.day_overtime,
        night_ordinary=payload.night_ordinary,
        night_overtime=payload.night_overtime,
        active=payload.active,
        position=payload.position if payload.position is not None else max_pos + 1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/rates/{rate_id}", response_model=LabourRateOut)
def update_rate(rate_id: int, payload: LabourRateIn, db: Session = Depends(get_db)):
    row = db.get(LabourRate, rate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    clash = (
        db.query(LabourRate)
        .filter(
            func.lower(LabourRate.name) == payload.name.strip().lower(),
            LabourRate.id != rate_id,
        )
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="A rate category with this name already exists")
    row.name = payload.name.strip()
    row.day_ordinary = payload.day_ordinary
    row.day_overtime = payload.day_overtime
    row.night_ordinary = payload.night_ordinary
    row.night_overtime = payload.night_overtime
    row.active = payload.active
    if payload.position is not None:
        row.position = payload.position
    db.commit()
    db.refresh(row)
    return row


@router.delete("/rates/{rate_id}", status_code=204)
def delete_rate(rate_id: int, db: Session = Depends(get_db)):
    row = db.get(LabourRate, rate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Rate not found")
    db.delete(row)
    db.commit()
    return None


@router.post("/calculate/standard")
def calc_standard(payload: dict, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    rates = db.query(LabourRate).filter(LabourRate.active.is_(True)).all()
    try:
        return calculate_standard(payload, settings, rates)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calculate/closure-24h")
def calc_closure(payload: dict, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    rates = db.query(LabourRate).filter(LabourRate.active.is_(True)).all()
    try:
        return calculate_closure_24h(payload, settings, rates)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/estimates")
def list_estimates(site_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(CostEstimate)
    if site_id is not None:
        q = q.filter(CostEstimate.site_id == site_id)
    rows = q.order_by(CostEstimate.created_at.desc()).limit(100).all()
    return [
        {
            "id": r.id,
            "site_id": r.site_id,
            "name": r.name,
            "mode": r.mode,
            "inputs": r.inputs,
            "results": r.results,
            "created_by": r.created_by,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.post("/estimates", status_code=201)
def save_estimate(payload: EstimateSave, db: Session = Depends(get_db)):
    if payload.site_id is not None and not db.get(Site, payload.site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    row = CostEstimate(
        site_id=payload.site_id,
        name=payload.name.strip(),
        mode=payload.mode,
        inputs=payload.inputs,
        results=payload.results,
        created_by=payload.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "site_id": row.site_id,
        "name": row.name,
        "mode": row.mode,
        "created_at": row.created_at,
    }


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: int, db: Session = Depends(get_db)):
    row = db.get(CostEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")
    db.delete(row)
    db.commit()
    return None
