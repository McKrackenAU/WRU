"""Admin settings + lookup lists (roads, councils)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..models import LookupItem
from ..schemas import AppSettingsOut, AppSettingsUpdate, LookupIn, LookupOut
from ..settings_store import ensure_settings, get_rules, update_settings
from ..stage_registry import ensure_lookup_seed

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/settings", response_model=AppSettingsOut)
def get_app_settings(db: Session = Depends(get_db)):
    return get_rules(db).as_dict()


@router.put("/settings", response_model=AppSettingsOut)
def put_app_settings(payload: AppSettingsUpdate, db: Session = Depends(get_db)):
    ensure_settings(db)
    row = update_settings(db, payload.model_dump(exclude_unset=True))
    return get_rules(db).as_dict()


@router.get("/lookups", response_model=list[LookupOut])
def list_lookups(
    kind: str | None = Query(default=None, pattern="^(road|council)$"),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    ensure_lookup_seed(db)
    q = db.query(LookupItem)
    if kind:
        q = q.filter(LookupItem.kind == kind)
    if active_only:
        q = q.filter(LookupItem.active.is_(True))
    return q.order_by(LookupItem.kind.asc(), LookupItem.position.asc(), LookupItem.value.asc()).all()


@router.post("/lookups", response_model=LookupOut, status_code=201)
def create_lookup(payload: LookupIn, db: Session = Depends(get_db)):
    value = payload.value.strip()
    exists = (
        db.query(LookupItem)
        .filter(LookupItem.kind == payload.kind, LookupItem.value.ilike(value))
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Lookup value already exists")
    max_pos = (
        db.query(LookupItem)
        .filter(LookupItem.kind == payload.kind)
        .count()
    )
    row = LookupItem(
        kind=payload.kind,
        value=value,
        position=payload.position if payload.position is not None else (max_pos + 1) * 10,
        active=payload.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/lookups/{lookup_id}", response_model=LookupOut)
def update_lookup(lookup_id: int, payload: LookupIn, db: Session = Depends(get_db)):
    row = db.get(LookupItem, lookup_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lookup not found")
    row.kind = payload.kind
    row.value = payload.value.strip()
    if payload.position is not None:
        row.position = payload.position
    row.active = payload.active
    db.commit()
    db.refresh(row)
    return row


@router.delete("/lookups/{lookup_id}", status_code=204)
def delete_lookup(lookup_id: int, db: Session = Depends(get_db)):
    row = db.get(LookupItem, lookup_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lookup not found")
    row.active = False
    db.commit()
