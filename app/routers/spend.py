"""Actual spend tracking + traffic contractor admin list."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from ..asphalt_engine import calculate_asphalt
from ..cost_engine import calculate_standard
from ..database import get_db
from ..models import (
    ActualSpend,
    AsphaltRate,
    AsphaltSubcontractor,
    LabourRate,
    Site,
    TrafficContractor,
)
from ..routers.costs import get_or_create_settings
from ..spend_export import build_spend_pdf, build_spend_workbook
from ..spend_from_estimates import sync_spend_from_estimates

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
    amount: float | None = Field(default=None, ge=0)
    source: str = Field(default="manual", pattern="^(manual|calculated|from_estimate)$")
    category: str | None = Field(default=None, max_length=64)
    traffic_contractor_id: int | None = None
    asphalt_subcontractor_id: int | None = None
    invoice_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = None
    created_by: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class SpendPatch(BaseModel):
    kind: str | None = Field(default=None, pattern="^(traffic|asphalt)$")
    site_id: int | None = None
    work_date: date | None = None
    amount: float | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, pattern="^(manual|calculated|from_estimate)$")
    category: str | None = None
    traffic_contractor_id: int | None = None
    asphalt_subcontractor_id: int | None = None
    invoice_ref: str | None = None
    notes: str | None = None
    created_by: str | None = None
    inputs: dict[str, Any] | None = None


class SpendPreviewIn(BaseModel):
    kind: str = Field(pattern="^(traffic|asphalt)$")
    work_date: date | None = None
    asphalt_subcontractor_id: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


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
        "source": getattr(row, "source", None) or "manual",
        "category": row.category,
        "traffic_contractor_id": row.traffic_contractor_id,
        "asphalt_subcontractor_id": row.asphalt_subcontractor_id,
        "invoice_ref": row.invoice_ref,
        "notes": row.notes,
        "inputs": getattr(row, "inputs", None) or {},
        "results": getattr(row, "results", None) or {},
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "road_name": site.road_name if site else None,
        "site_number": site.site_number if site else None,
        "program": site.program if site else None,
        "contractor_name": contractor,
    }


def _hydrate_asphalt_lines(db: Session, lines: list[dict[str, Any]], subcontractor_id: int | None) -> list[dict]:
    out: list[dict[str, Any]] = []
    for raw in lines or []:
        if not isinstance(raw, dict):
            continue
        line = dict(raw)
        rate_id = line.get("rate_id")
        if rate_id:
            rate = db.get(AsphaltRate, int(rate_id))
            if not rate or not rate.active:
                raise HTTPException(status_code=404, detail=f"Asphalt rate {rate_id} not found")
            if subcontractor_id and rate.subcontractor_id != subcontractor_id:
                raise HTTPException(status_code=400, detail="Rate does not belong to selected subcontractor")
            line.setdefault("name", rate.name)
            line.setdefault("unit", rate.unit)
            line["rate_type"] = getattr(rate, "rate_type", None) or "unit"
            line["day_rate"] = rate.day_rate
            line["night_rate"] = rate.night_rate
            line["saturday_rate"] = rate.saturday_rate
            line["sunday_rate"] = rate.sunday_rate
            line["public_holiday_rate"] = rate.public_holiday_rate
        out.append(line)
    return out


def _calculate_spend(
    db: Session,
    *,
    kind: str,
    work_date: date | None,
    asphalt_subcontractor_id: int | None,
    inputs: dict[str, Any],
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    """Return (amount, stored_inputs, results) using live rate cards."""
    raw_inputs = dict(inputs or {})
    if kind == "traffic":
        settings = get_or_create_settings(db)
        rates = db.query(LabourRate).filter(LabourRate.active.is_(True)).all()
        day = (work_date or date.today()).isoformat()
        payload = {
            "works_start": day,
            "work_dates": [day],
            "days_of_work": 1,
            "shifts_per_day": int(raw_inputs.get("shifts_per_day") or 1),
            "shift_hours": float(raw_inputs.get("shift_hours") or 10),
            "shift_type": (raw_inputs.get("shift_type") or "day").strip().lower(),
            "shift_start_time": raw_inputs.get("shift_start_time") or "07:00",
            "overtime_after_hours": float(
                raw_inputs.get("overtime_after_hours") or settings.overtime_after_hours or 8
            ),
            "resources": {
                "people": int((raw_inputs.get("resources") or {}).get("people") or raw_inputs.get("people") or 0),
                "vehicles": int(
                    (raw_inputs.get("resources") or {}).get("vehicles") or raw_inputs.get("vehicles") or 0
                ),
                "tmas": int((raw_inputs.get("resources") or {}).get("tmas") or raw_inputs.get("tmas") or 0),
                "spotters": int(
                    (raw_inputs.get("resources") or {}).get("spotters") or raw_inputs.get("spotters") or 0
                ),
            },
            "vms_quantity": int(raw_inputs.get("vms_quantity") or 0),
            "vms_lead_days": int(raw_inputs.get("vms_lead_days") or settings.vms_lead_days_default or 0),
        }
        if raw_inputs.get("crew"):
            payload["crew"] = raw_inputs["crew"]
        try:
            results = calculate_standard(payload, settings, rates)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        amount = float(results.get("site_traffic_total") or results.get("site_crew_total") or 0)
        return round(amount, 2), payload, results

    # asphalt
    lines = _hydrate_asphalt_lines(db, list(raw_inputs.get("lines") or []), asphalt_subcontractor_id)
    if not lines:
        raise HTTPException(status_code=400, detail="Add at least one asphalt rate line")
    payload = {
        "subcontractor_id": asphalt_subcontractor_id,
        "shift_type": (raw_inputs.get("shift_type") or "day").strip().lower(),
        "rate_tier": (raw_inputs.get("rate_tier") or "").strip().lower() or None,
        "contingency_pct": float(raw_inputs.get("contingency_pct") or 0),
        "lines": lines,
        "work_date": work_date.isoformat() if work_date else None,
    }
    # Auto tier from work date when not night and no override
    if not payload["rate_tier"] and work_date and payload["shift_type"] != "night":
        wd = work_date.weekday()  # Mon=0
        if wd == 5:
            payload["rate_tier"] = "saturday"
        elif wd == 6:
            payload["rate_tier"] = "sunday"
    try:
        results = calculate_asphalt(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if asphalt_subcontractor_id:
        sub = db.get(AsphaltSubcontractor, asphalt_subcontractor_id)
        if sub:
            results["subcontractor_name"] = sub.name
    amount = float(results.get("total") or 0)
    return round(amount, 2), payload, results


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
    sync_estimates: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    if sync_estimates:
        # Keep site-level actuals aligned with latest saved estimates
        sync_spend_from_estimates(db, site_id=site_id)
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


@router.post("/spend/sync-from-estimates")
def sync_from_estimates(
    site_id: int | None = None,
    db: Session = Depends(get_db),
):
    if site_id is not None and not db.get(Site, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return sync_spend_from_estimates(db, site_id=site_id)


def _load_spend(db: Session, spend_id: int) -> ActualSpend:
    return (
        db.query(ActualSpend)
        .options(
            selectinload(ActualSpend.site),
            selectinload(ActualSpend.traffic_contractor),
            selectinload(ActualSpend.asphalt_subcontractor),
        )
        .filter(ActualSpend.id == spend_id)
        .one()
    )


@router.post("/spend/preview")
def preview_spend(payload: SpendPreviewIn, db: Session = Depends(get_db)):
    amount, inputs, results = _calculate_spend(
        db,
        kind=payload.kind,
        work_date=payload.work_date,
        asphalt_subcontractor_id=payload.asphalt_subcontractor_id if payload.kind == "asphalt" else None,
        inputs=payload.inputs or {},
    )
    return {"amount": amount, "inputs": inputs, "results": results}


@router.post("/spend", status_code=201)
def create_spend(payload: SpendIn, db: Session = Depends(get_db)):
    if not db.get(Site, payload.site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    if payload.traffic_contractor_id and not db.get(TrafficContractor, payload.traffic_contractor_id):
        raise HTTPException(status_code=404, detail="Traffic contractor not found")
    if payload.asphalt_subcontractor_id and not db.get(AsphaltSubcontractor, payload.asphalt_subcontractor_id):
        raise HTTPException(status_code=404, detail="Asphalt subcontractor not found")

    source = payload.source or "manual"
    inputs = dict(payload.inputs or {})
    results: dict[str, Any] = {}
    amount = payload.amount
    if source == "calculated":
        amount, inputs, results = _calculate_spend(
            db,
            kind=payload.kind,
            work_date=payload.work_date,
            asphalt_subcontractor_id=payload.asphalt_subcontractor_id if payload.kind == "asphalt" else None,
            inputs=inputs,
        )
    elif amount is None:
        raise HTTPException(status_code=400, detail="Amount is required for manual spend")

    row = ActualSpend(
        kind=payload.kind,
        site_id=payload.site_id,
        work_date=payload.work_date,
        amount=float(amount or 0),
        source=source,
        category=(payload.category or "").strip() or None,
        traffic_contractor_id=payload.traffic_contractor_id if payload.kind == "traffic" else None,
        asphalt_subcontractor_id=payload.asphalt_subcontractor_id if payload.kind == "asphalt" else None,
        invoice_ref=(payload.invoice_ref or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        inputs=inputs,
        results=results,
        created_by=(payload.created_by or "").strip() or None,
    )
    db.add(row)
    db.commit()
    return _spend_public(_load_spend(db, row.id))


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

    recalc_keys = {"source", "inputs", "work_date", "kind", "asphalt_subcontractor_id"}
    for key, value in data.items():
        if key in {"inputs", "results"}:
            continue
        if isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    if "inputs" in data and data["inputs"] is not None:
        row.inputs = dict(data["inputs"])

    if row.kind == "traffic":
        row.asphalt_subcontractor_id = None
    else:
        row.traffic_contractor_id = None

    source = row.source or "manual"
    if source == "calculated" and (recalc_keys & set(data.keys())):
        amount, inputs, results = _calculate_spend(
            db,
            kind=row.kind,
            work_date=row.work_date,
            asphalt_subcontractor_id=row.asphalt_subcontractor_id if row.kind == "asphalt" else None,
            inputs=row.inputs or {},
        )
        row.amount = amount
        row.inputs = inputs
        row.results = results
        row.source = "calculated"
    elif source == "manual" and "source" in data:
        row.results = {}

    db.commit()
    return _spend_public(_load_spend(db, spend_id))


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
