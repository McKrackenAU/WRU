"""Actual spend tracking + traffic contractor admin list."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import ActualSpend, AsphaltSubcontractor, Site, TrafficContractor
from ..spend_export import build_spend_pdf, build_spend_workbook

router = APIRouter(prefix="/api", tags=["spend"])


class TrafficContractorIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    notes: str | None = None
    active: bool = True
    position: int | None = None


class TrafficContractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    notes: str | None = None
    active: bool
    position: int


class SpendIn(BaseModel):
    kind: str = Field(pattern="^(traffic|asphalt)$")
    site_id: int
    work_date: date | None = None
    amount: float = Field(ge=0)
    category: str | None = Field(default=None, max_length=64)
    traffic_contractor_id: int | None = None
    asphalt_subcontractor_id: int | None = None
    invoice_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = None
    created_by: str | None = None


class SpendPatch(BaseModel):
    kind: str | None = Field(default=None, pattern="^(traffic|asphalt)$")
    site_id: int | None = None
    work_date: date | None = None
    amount: float | None = Field(default=None, ge=0)
    category: str | None = None
    traffic_contractor_id: int | None = None
    asphalt_subcontractor_id: int | None = None
    invoice_ref: str | None = None
    notes: str | None = None
    created_by: str | None = None


def _spend_public(row: ActualSpend) -> dict:
    site = row.site
    if row.kind == "asphalt":
        contractor = row.asphalt_subcontractor.name if row.asphalt_subcontractor else None
    else:
        contractor = row.traffic_contractor.name if row.traffic_contractor else None
    return {
        "id": row.id,
        "kind": row.kind,
        "site_id": row.site_id,
        "work_date": row.work_date.isoformat() if row.work_date else None,
        "amount": float(row.amount or 0),
        "category": row.category,
        "traffic_contractor_id": row.traffic_contractor_id,
        "asphalt_subcontractor_id": row.asphalt_subcontractor_id,
        "invoice_ref": row.invoice_ref,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
        "program": site.program if site else None,
        "contractor_name": contractor,
    }


def _spend_query(
    db: Session,
    *,
    kind: str | None = None,
    site_id: int | None = None,
    traffic_contractor_id: int | None = None,
    asphalt_subcontractor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    q = (
        db.query(ActualSpend)
        .options(
            selectinload(ActualSpend.site),
            selectinload(ActualSpend.traffic_contractor),
            selectinload(ActualSpend.asphalt_subcontractor),
        )
        .order_by(ActualSpend.work_date.desc().nullslast(), ActualSpend.id.desc())
    )
    if kind:
        q = q.filter(ActualSpend.kind == kind)
    if site_id:
        q = q.filter(ActualSpend.site_id == site_id)
    if traffic_contractor_id:
        q = q.filter(ActualSpend.traffic_contractor_id == traffic_contractor_id)
    if asphalt_subcontractor_id:
        q = q.filter(ActualSpend.asphalt_subcontractor_id == asphalt_subcontractor_id)
    if date_from:
        q = q.filter(ActualSpend.work_date >= date_from)
    if date_to:
        q = q.filter(ActualSpend.work_date <= date_to)
    return q


# --- Traffic contractors ---


@router.get("/traffic-contractors", response_model=list[TrafficContractorOut])
def list_traffic_contractors(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    q = db.query(TrafficContractor).order_by(TrafficContractor.position.asc(), TrafficContractor.id.asc())
    if active_only:
        q = q.filter(TrafficContractor.active.is_(True))
    return q.all()


@router.post("/traffic-contractors", response_model=TrafficContractorOut, status_code=201)
def create_traffic_contractor(payload: TrafficContractorIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if db.query(TrafficContractor).filter(func.lower(TrafficContractor.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="Traffic contractor already exists")
    max_pos = db.query(func.max(TrafficContractor.position)).scalar() or 0
    row = TrafficContractor(
        name=name,
        notes=(payload.notes or "").strip() or None,
        active=payload.active,
        position=payload.position if payload.position is not None else max_pos + 10,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/traffic-contractors/{contractor_id}", response_model=TrafficContractorOut)
def update_traffic_contractor(
    contractor_id: int, payload: TrafficContractorIn, db: Session = Depends(get_db)
):
    row = db.get(TrafficContractor, contractor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    name = payload.name.strip()
    clash = (
        db.query(TrafficContractor)
        .filter(func.lower(TrafficContractor.name) == name.lower(), TrafficContractor.id != contractor_id)
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="Traffic contractor already exists")
    row.name = name
    row.notes = (payload.notes or "").strip() or None
    row.active = payload.active
    if payload.position is not None:
        row.position = payload.position
    db.commit()
    db.refresh(row)
    return row


@router.delete("/traffic-contractors/{contractor_id}", status_code=204)
def delete_traffic_contractor(contractor_id: int, db: Session = Depends(get_db)):
    row = db.get(TrafficContractor, contractor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    row.active = False
    db.commit()
    return None


# --- Actual spend ---


@router.get("/spend")
def list_spend(
    kind: str | None = Query(default=None, pattern="^(traffic|asphalt)$"),
    site_id: int | None = None,
    traffic_contractor_id: int | None = None,
    asphalt_subcontractor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    rows = _spend_query(
        db,
        kind=kind,
        site_id=site_id,
        traffic_contractor_id=traffic_contractor_id,
        asphalt_subcontractor_id=asphalt_subcontractor_id,
        date_from=date_from,
        date_to=date_to,
    ).all()
    return [_spend_public(r) for r in rows]


@router.post("/spend", status_code=201)
def create_spend(payload: SpendIn, db: Session = Depends(get_db)):
    if not db.get(Site, payload.site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    if payload.traffic_contractor_id and not db.get(TrafficContractor, payload.traffic_contractor_id):
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    if payload.asphalt_subcontractor_id and not db.get(AsphaltSubcontractor, payload.asphalt_subcontractor_id):
        raise HTTPException(status_code=404, detail="Asphalt subcontractor not found")
    row = ActualSpend(
        kind=payload.kind,
        site_id=payload.site_id,
        work_date=payload.work_date,
        amount=float(payload.amount or 0),
        category=(payload.category or "").strip() or None,
        traffic_contractor_id=payload.traffic_contractor_id if payload.kind == "traffic" else None,
        asphalt_subcontractor_id=payload.asphalt_subcontractor_id if payload.kind == "asphalt" else None,
        invoice_ref=(payload.invoice_ref or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        created_by=(payload.created_by or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row = (
        db.query(ActualSpend)
        .options(
            selectinload(ActualSpend.site),
            selectinload(ActualSpend.traffic_contractor),
            selectinload(ActualSpend.asphalt_subcontractor),
        )
        .filter(ActualSpend.id == row.id)
        .one()
    )
    return _spend_public(row)


@router.patch("/spend/{spend_id}")
def patch_spend(spend_id: int, payload: SpendPatch, db: Session = Depends(get_db)):
    row = db.get(ActualSpend, spend_id)
    if not row:
        raise HTTPException(status_code=404, detail="Spend row not found")
    data = payload.model_dump(exclude_unset=True)
    if "site_id" in data and data["site_id"] is not None and not db.get(Site, data["site_id"]):
        raise HTTPException(status_code=404, detail="Site not found")
    if data.get("traffic_contractor_id") and not db.get(TrafficContractor, data["traffic_contractor_id"]):
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    if data.get("asphalt_subcontractor_id") and not db.get(
        AsphaltSubcontractor, data["asphalt_subcontractor_id"]
    ):
        raise HTTPException(status_code=404, detail="Asphalt subcontractor not found")
    for key, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    if row.kind == "traffic":
        row.asphalt_subcontractor_id = None
    else:
        row.traffic_contractor_id = None
    db.commit()
    row = (
        db.query(ActualSpend)
        .options(
            selectinload(ActualSpend.site),
            selectinload(ActualSpend.traffic_contractor),
            selectinload(ActualSpend.asphalt_subcontractor),
        )
        .filter(ActualSpend.id == spend_id)
        .one()
    )
    return _spend_public(row)


@router.delete("/spend/{spend_id}", status_code=204)
def delete_spend(spend_id: int, db: Session = Depends(get_db)):
    row = db.get(ActualSpend, spend_id)
    if not row:
        raise HTTPException(status_code=404, detail="Spend row not found")
    db.delete(row)
    db.commit()
    return None


def _export_rows(
    db: Session,
    *,
    kind: str | None,
    site_id: int | None,
    traffic_contractor_id: int | None,
    asphalt_subcontractor_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> list[dict]:
    rows = _spend_query(
        db,
        kind=kind,
        site_id=site_id,
        traffic_contractor_id=traffic_contractor_id,
        asphalt_subcontractor_id=asphalt_subcontractor_id,
        date_from=date_from,
        date_to=date_to,
    ).all()
    return [_spend_public(r) for r in rows]


@router.get("/spend/export.xlsx")
def export_spend_xlsx(
    kind: str | None = Query(default=None, pattern="^(traffic|asphalt)$"),
    site_id: int | None = None,
    traffic_contractor_id: int | None = None,
    asphalt_subcontractor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    rows = _export_rows(
        db,
        kind=kind,
        site_id=site_id,
        traffic_contractor_id=traffic_contractor_id,
        asphalt_subcontractor_id=asphalt_subcontractor_id,
        date_from=date_from,
        date_to=date_to,
    )
    title = "Actual spend"
    if kind == "traffic":
        title = "Actual traffic spend"
    elif kind == "asphalt":
        title = "Actual pavements / asphalt spend"
    data = build_spend_workbook(rows, title=title)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="actual-spend.xlsx"'},
    )


@router.get("/spend/export.pdf")
def export_spend_pdf(
    kind: str | None = Query(default=None, pattern="^(traffic|asphalt)$"),
    site_id: int | None = None,
    traffic_contractor_id: int | None = None,
    asphalt_subcontractor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    rows = _export_rows(
        db,
        kind=kind,
        site_id=site_id,
        traffic_contractor_id=traffic_contractor_id,
        asphalt_subcontractor_id=asphalt_subcontractor_id,
        date_from=date_from,
        date_to=date_to,
    )
    title = "Actual spend"
    if kind == "traffic":
        title = "Actual traffic spend"
    elif kind == "asphalt":
        title = "Actual pavements / asphalt spend"
    data = build_spend_pdf(rows, title=title)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="actual-spend.pdf"'},
    )
