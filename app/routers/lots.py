"""Lot register for shift QA."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..lot_register import sync_lot
from ..models import LotRegister, ShiftReport, User

router = APIRouter(prefix="/api/lots", tags=["lots"])

QA_STATES = {"pending", "accepted", "hold"}


def _public(row: LotRegister) -> dict:
    return {
        "id": row.id,
        "lot_number": row.lot_number,
        "site_id": row.site_id,
        "shift_id": row.shift_id,
        "work_date": row.work_date.isoformat() if row.work_date else None,
        "road_name": row.road_name,
        "road_number": row.road_number,
        "fmrp_year": row.fmrp_year,
        "site_number": row.site_number,
        "work_kind": row.work_kind,
        "mix": row.mix,
        "supervisor": row.supervisor,
        "qa_status": row.qa_status,
        "qa_notes": row.qa_notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class LotPatch(BaseModel):
    qa_status: str | None = Field(default=None, pattern="^(pending|accepted|hold)$")
    qa_notes: str | None = None


@router.get("")
def list_lots(
    site_id: int | None = None,
    work_kind: str | None = None,
    mix: str | None = None,
    qa_status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    missing = (
        db.query(ShiftReport)
        .outerjoin(LotRegister, LotRegister.shift_id == ShiftReport.id)
        .filter(LotRegister.id.is_(None))
        .limit(200)
        .all()
    )
    if missing:
        for report in missing:
            sync_lot(db, report)
        db.commit()
    query = db.query(LotRegister)
    if site_id:
        query = query.filter(LotRegister.site_id == site_id)
    if work_kind in {"hma", "pro"}:
        query = query.filter(LotRegister.work_kind == work_kind)
    if mix:
        query = query.filter(LotRegister.mix.ilike(mix.strip()))
    if qa_status in QA_STATES:
        query = query.filter(LotRegister.qa_status == qa_status)
    rows = query.order_by(LotRegister.work_date.desc(), LotRegister.id.desc()).limit(400).all()
    return [_public(row) for row in rows]


@router.patch("/{lot_id}")
def update_lot(
    lot_id: int,
    payload: LotPatch,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.get(LotRegister, lot_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lot not found")
    data = payload.model_dump(exclude_unset=True)
    if "qa_status" in data and data["qa_status"]:
        row.qa_status = data["qa_status"]
    if "qa_notes" in data:
        row.qa_notes = (data["qa_notes"] or "").strip() or None
    db.commit()
    db.refresh(row)
    return _public(row)
