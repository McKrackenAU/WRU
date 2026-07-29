from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..cost_engine import calculate_closure_24h, calculate_standard
from ..database import UPLOAD_DIR, get_db
from ..models import CostEstimate, CostEstimateAttachment, CostSettings, LabourRate, Site

router = APIRouter(prefix="/api/costs", tags=["costs"])

ESTIMATE_UPLOAD_DIR = UPLOAD_DIR / "cost-estimates"
ESTIMATE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class CostSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    overtime_after_hours: float
    vms_lead_days_default: int
    vms_delivery_rate: float
    vms_collection_rate: float
    vms_day_rate: float
    travel_allowance: float
    meal_allowance: float
    meal_after_hours: float


class CostSettingsUpdate(BaseModel):
    overtime_after_hours: float | None = Field(default=None, gt=0, le=24)
    vms_lead_days_default: int | None = Field(default=None, ge=0, le=60)
    vms_delivery_rate: float | None = Field(default=None, ge=0)
    vms_collection_rate: float | None = Field(default=None, ge=0)
    vms_day_rate: float | None = Field(default=None, ge=0)
    travel_allowance: float | None = Field(default=None, ge=0)
    meal_allowance: float | None = Field(default=None, ge=0)
    meal_after_hours: float | None = Field(default=None, gt=0, le=24)


class LabourRateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    rate_kind: str = Field(default="crew_pack", pattern="^(crew_pack|tma|spotter|legacy)$")
    pack_people: int = Field(default=1, ge=0, le=4)
    includes_vehicle: bool = False
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
    site_id: int = Field(..., description="MoA / site this estimate belongs to")
    mode: str
    notes: str | None = None
    inputs: dict
    results: dict
    created_by: str | None = None


class EstimateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: int | None = None
    notes: str | None = None


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
        travel_allowance=45.0,
        meal_allowance=30.0,
        meal_after_hours=9.5,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _pack_seed_rows() -> list[dict]:
    """Starter TC packs (1–4 ± vehicle), TMA, and Spotter cards.

    Dollar values are placeholders — edit on the Rates page to match your
    schedule. Pack pricing is intentionally non-linear so the allocator can
    prefer larger packs when they are cheaper.
    """
    rows: list[dict] = []
    # people, includes_vehicle, day_o, day_ot, night_o, night_ot
    matrix = [
        (1, False, 55, 75, 70, 95),
        (2, False, 100, 140, 130, 180),
        (3, False, 145, 200, 185, 255),
        (4, False, 180, 250, 230, 320),
        (1, True, 80, 100, 100, 125),
        (2, True, 130, 170, 160, 210),
        (3, True, 175, 230, 210, 285),
        (4, True, 210, 280, 255, 350),
    ]
    for people, with_veh, d_o, d_ot, n_o, n_ot in matrix:
        label = f"{people} TC"
        label += " + vehicle" if with_veh else " (no vehicle)"
        rows.append(
            {
                "name": label,
                "rate_kind": "crew_pack",
                "pack_people": people,
                "includes_vehicle": with_veh,
                "day_ordinary": d_o,
                "day_overtime": d_ot,
                "night_ordinary": n_o,
                "night_overtime": n_ot,
            }
        )
    rows.append(
        {
            "name": "TMA (incl. driver)",
            "rate_kind": "tma",
            "pack_people": 0,
            "includes_vehicle": True,
            "day_ordinary": 180,
            "day_overtime": 220,
            "night_ordinary": 210,
            "night_overtime": 260,
        }
    )
    rows.append(
        {
            "name": "Spotter",
            "rate_kind": "spotter",
            "pack_people": 1,
            "includes_vehicle": False,
            "day_ordinary": 50,
            "day_overtime": 70,
            "night_ordinary": 65,
            "night_overtime": 90,
        }
    )
    return rows


def _add_rate_if_missing(db: Session, row: dict, position: int) -> bool:
    if db.query(LabourRate).filter(func.lower(LabourRate.name) == row["name"].lower()).first():
        return False
    db.add(
        LabourRate(
            name=row["name"],
            rate_kind=row["rate_kind"],
            pack_people=row["pack_people"],
            includes_vehicle=row["includes_vehicle"],
            day_ordinary=row["day_ordinary"],
            day_overtime=row["day_overtime"],
            night_ordinary=row["night_ordinary"],
            night_overtime=row["night_overtime"],
            active=True,
            position=position,
        )
    )
    return True


def ensure_default_rates(db: Session) -> None:
    """Seed TC pack / TMA / Spotter catalogue when missing (keeps legacy rows)."""
    has_packs = db.query(LabourRate).filter(LabourRate.rate_kind == "crew_pack").count()
    max_pos = db.query(func.max(LabourRate.position)).scalar() or 0
    added = 0
    seed_rows = _pack_seed_rows()
    if not has_packs:
        for row in seed_rows:
            max_pos += 1
            if _add_rate_if_missing(db, row, max_pos):
                added += 1
    else:
        for row in seed_rows:
            if row["rate_kind"] in ("tma", "spotter"):
                max_pos += 1
                if _add_rate_if_missing(db, row, max_pos):
                    added += 1
    if added:
        db.commit()


def _summary_total(mode: str, results: dict) -> float | None:
    if mode == "standard":
        return results.get("site_traffic_total")
    a = (results.get("option_3x8") or {}).get("grand_total")
    b = (results.get("option_2x12") or {}).get("grand_total")
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


def _attachment_out(att: CostEstimateAttachment) -> dict:
    return {
        "id": att.id,
        "estimate_id": att.estimate_id,
        "original_filename": att.original_filename,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "description": att.description,
        "uploaded_by": att.uploaded_by,
        "uploaded_at": att.uploaded_at,
    }


def _estimate_out(row: CostEstimate, *, include_results: bool = True) -> dict:
    site = row.site
    payload = {
        "id": row.id,
        "site_id": row.site_id,
        "name": row.name,
        "mode": row.mode,
        "notes": row.notes,
        "moa_number": row.moa_number or (site.moa_number if site else None),
        "summary_total": row.summary_total,
        "inputs": row.inputs,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "attachment_count": len(row.attachments or []),
        "attachments": [_attachment_out(a) for a in (row.attachments or [])],
        "road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
        "tgs_reference": site.tgs_reference if site else None,
    }
    if include_results:
        payload["results"] = row.results
    return payload


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


def _validate_rate_payload(payload: LabourRateIn) -> None:
    if payload.rate_kind == "crew_pack" and not (1 <= payload.pack_people <= 4):
        raise HTTPException(status_code=400, detail="Crew packs must cover 1–4 TCs")
    if payload.rate_kind == "tma" and payload.pack_people != 0:
        raise HTTPException(status_code=400, detail="TMA rates should use pack_people = 0 (driver included)")
    if payload.rate_kind == "spotter" and payload.pack_people != 1:
        raise HTTPException(status_code=400, detail="Spotter rates should use pack_people = 1")


@router.post("/rates", response_model=LabourRateOut, status_code=201)
def create_rate(payload: LabourRateIn, db: Session = Depends(get_db)):
    _validate_rate_payload(payload)
    if db.query(LabourRate).filter(func.lower(LabourRate.name) == payload.name.strip().lower()).first():
        raise HTTPException(status_code=400, detail="A rate category with this name already exists")
    max_pos = db.query(func.max(LabourRate.position)).scalar() or 0
    row = LabourRate(
        name=payload.name.strip(),
        rate_kind=payload.rate_kind,
        pack_people=payload.pack_people,
        includes_vehicle=payload.includes_vehicle,
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
    _validate_rate_payload(payload)
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
    row.rate_kind = payload.rate_kind
    row.pack_people = payload.pack_people
    row.includes_vehicle = payload.includes_vehicle
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
def list_estimates(
    site_id: int | None = None,
    moa_number: str | None = None,
    q: str | None = None,
    include_unassigned: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    query = db.query(CostEstimate)
    if site_id is not None:
        query = query.filter(CostEstimate.site_id == site_id)
    elif not include_unassigned:
        query = query.filter(CostEstimate.site_id.isnot(None))
    if moa_number:
        query = query.outerjoin(Site).filter(
            (CostEstimate.moa_number == moa_number.strip())
            | (Site.moa_number == moa_number.strip())
        )
    if q:
        like = f"%{q.strip()}%"
        query = query.outerjoin(Site).filter(
            CostEstimate.name.ilike(like)
            | CostEstimate.notes.ilike(like)
            | CostEstimate.moa_number.ilike(like)
            | Site.road_name.ilike(like)
            | Site.site_number.ilike(like)
            | Site.moa_number.ilike(like)
        )
    rows = query.order_by(CostEstimate.created_at.desc()).limit(200).all()
    return [_estimate_out(r, include_results=False) for r in rows]


@router.get("/estimates/{estimate_id}")
def get_estimate(estimate_id: int, db: Session = Depends(get_db)):
    row = db.get(CostEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return _estimate_out(row, include_results=True)


@router.post("/estimates", status_code=201)
def save_estimate(payload: EstimateSave, db: Session = Depends(get_db)):
    site = db.get(Site, payload.site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    summary = _summary_total(payload.mode, payload.results or {})
    row = CostEstimate(
        site_id=site.id,
        name=payload.name.strip(),
        mode=payload.mode,
        notes=(payload.notes or "").strip() or None,
        moa_number=site.moa_number,
        summary_total=summary,
        inputs=payload.inputs,
        results=payload.results,
        created_by=payload.created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _estimate_out(row, include_results=True)


@router.patch("/estimates/{estimate_id}")
def update_estimate(estimate_id: int, payload: EstimateUpdate, db: Session = Depends(get_db)):
    row = db.get(CostEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")
    data = payload.model_dump(exclude_unset=True)
    if "site_id" in data:
        site_id = data["site_id"]
        if site_id is not None:
            site = db.get(Site, site_id)
            if not site:
                raise HTTPException(status_code=404, detail="Site not found")
            row.site_id = site_id
            row.moa_number = site.moa_number
        else:
            row.site_id = None
    if "name" in data and data["name"] is not None:
        row.name = data["name"].strip()
    if "notes" in data:
        row.notes = (data["notes"] or "").strip() or None
    db.commit()
    db.refresh(row)
    return _estimate_out(row, include_results=True)


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: int, db: Session = Depends(get_db)):
    row = db.get(CostEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")
    for att in list(row.attachments or []):
        (ESTIMATE_UPLOAD_DIR / att.stored_name).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return None


@router.post("/estimates/{estimate_id}/attachments", status_code=201)
async def upload_estimate_attachment(
    estimate_id: int,
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    row = db.get(CostEstimate, estimate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Estimate not found")

    original = Path(file.filename or "upload.bin").name
    suffix = Path(original).suffix[:32]
    stored_name = f"est{estimate_id}_{uuid.uuid4().hex}{suffix}"
    dest = ESTIMATE_UPLOAD_DIR / stored_name

    size = 0
    async with aiofiles.open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                await out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
            await out.write(chunk)

    att = CostEstimateAttachment(
        estimate_id=estimate_id,
        stored_name=stored_name,
        original_filename=original,
        content_type=file.content_type,
        size_bytes=size,
        description=(description or "").strip() or None,
        uploaded_by=uploaded_by,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return _attachment_out(att)


@router.get("/attachments/{attachment_id}/download")
def download_estimate_attachment(attachment_id: int, db: Session = Depends(get_db)):
    att = db.get(CostEstimateAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = ESTIMATE_UPLOAD_DIR / att.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(
        path,
        media_type=att.content_type or "application/octet-stream",
        filename=att.original_filename,
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_estimate_attachment(attachment_id: int, db: Session = Depends(get_db)):
    att = db.get(CostEstimateAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    (ESTIMATE_UPLOAD_DIR / att.stored_name).unlink(missing_ok=True)
    db.delete(att)
    db.commit()
    return None
