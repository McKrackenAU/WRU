"""Admin settings + lookup lists (roads, councils)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..live_hub import notify_from_request
from ..lookups import apply_lookup_update, usage_counts
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
    update_settings(db, payload.model_dump(exclude_unset=True))
    return get_rules(db).as_dict()


def _lookup_out(
    row: LookupItem,
    counts: dict[str, int],
    *,
    sites_updated: int = 0,
    merged: bool = False,
) -> LookupOut:
    return LookupOut(
        id=row.id,
        kind=row.kind,
        value=row.value,
        position=row.position,
        active=row.active,
        usage_count=counts.get(row.value.strip().lower(), 0),
        sites_updated=sites_updated,
        merged=merged,
    )


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
    rows = q.order_by(
        LookupItem.active.desc(),
        LookupItem.value.asc(),
        LookupItem.position.asc(),
    ).all()
    counts: dict[str, int] = {}
    kinds = {kind} if kind else {r.kind for r in rows} or {"road", "council"}
    for k in kinds:
        counts.update(usage_counts(db, k))
    return [_lookup_out(r, counts) for r in rows]


@router.post("/lookups", response_model=LookupOut, status_code=201)
def create_lookup(payload: LookupIn, request: Request, db: Session = Depends(get_db)):
    value = payload.value.strip()
    exists = (
        db.query(LookupItem)
        .filter(LookupItem.kind == payload.kind, LookupItem.value.ilike(value))
        .first()
    )
    if exists:
        if not exists.active:
            exists.active = True
            exists.value = value
            db.commit()
            db.refresh(exists)
            notify_from_request(request, reason="lookup")
            return _lookup_out(exists, usage_counts(db, exists.kind))
        raise HTTPException(status_code=409, detail="Lookup value already exists")
    max_pos = db.query(LookupItem).filter(LookupItem.kind == payload.kind).count()
    row = LookupItem(
        kind=payload.kind,
        value=value,
        position=payload.position if payload.position is not None else (max_pos + 1) * 10,
        active=payload.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    notify_from_request(request, reason="lookup")
    return _lookup_out(row, usage_counts(db, row.kind))


@router.patch("/lookups/{lookup_id}", response_model=LookupOut)
def update_lookup(lookup_id: int, payload: LookupIn, request: Request, db: Session = Depends(get_db)):
    row = db.get(LookupItem, lookup_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lookup not found")
    if payload.kind != row.kind:
        raise HTTPException(status_code=400, detail="Cannot change lookup kind")
    change = apply_lookup_update(
        db,
        row,
        value=payload.value,
        active=payload.active,
        position=payload.position,
    )
    notify_from_request(request, reason="lookup")
    return _lookup_out(
        change.row,
        usage_counts(db, change.row.kind),
        sites_updated=change.sites_updated,
        merged=change.merged,
    )


@router.delete("/lookups/{lookup_id}", status_code=204)
def delete_lookup(lookup_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(LookupItem, lookup_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lookup not found")
    row.active = False
    db.commit()
    notify_from_request(request, reason="lookup")
