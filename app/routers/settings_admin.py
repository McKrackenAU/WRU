"""Admin settings + lookup lists (roads, councils)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..doc_categories import (
    FALLBACK_KEY,
    all_doc_categories,
    ensure_doc_category_seed,
    reassign_documents,
    slug_category_key,
    usage_count,
)
from ..live_hub import notify_from_request
from ..lookups import apply_lookup_update, usage_counts
from ..models import DocumentCategoryDef, LookupItem
from ..schemas import AppSettingsOut, AppSettingsUpdate, LookupIn, LookupOut
from ..settings_store import ensure_settings, get_rules, update_settings
from ..stage_registry import ensure_lookup_seed
from ..storage_paths import describe_locations, upsert_location

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


class DocCategoryIn(BaseModel):
    key: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    position: int | None = None
    active: bool = True


class DocCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    position: int
    active: bool
    protected: bool
    usage_count: int = 0


def _doc_cat_out(row: DocumentCategoryDef, db: Session) -> DocCategoryOut:
    return DocCategoryOut(
        id=row.id,
        key=row.key,
        label=row.label,
        position=row.position,
        active=row.active,
        protected=row.protected,
        usage_count=usage_count(db, row.key),
    )


@router.get("/doc-categories", response_model=list[DocCategoryOut])
def list_doc_categories(
    include_inactive: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    ensure_doc_category_seed(db)
    rows = all_doc_categories(db)
    if not include_inactive:
        rows = [r for r in rows if r.active]
    return [_doc_cat_out(r, db) for r in rows]


@router.post("/doc-categories", response_model=DocCategoryOut, status_code=201)
def create_doc_category(payload: DocCategoryIn, request: Request, db: Session = Depends(get_db)):
    ensure_doc_category_seed(db)
    key = slug_category_key(payload.key or payload.label)
    exists = db.query(DocumentCategoryDef).filter(DocumentCategoryDef.key == key).first()
    if exists:
        if not exists.active:
            exists.active = True
            exists.label = payload.label.strip()
            db.commit()
            db.refresh(exists)
            notify_from_request(request, reason="doc-categories")
            return _doc_cat_out(exists, db)
        raise HTTPException(status_code=409, detail="That document type already exists")
    max_pos = db.query(func.max(DocumentCategoryDef.position)).scalar() or 0
    row = DocumentCategoryDef(
        key=key,
        label=payload.label.strip(),
        position=payload.position if payload.position is not None else max_pos + 10,
        active=payload.active,
        protected=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    notify_from_request(request, reason="doc-categories")
    return _doc_cat_out(row, db)


@router.patch("/doc-categories/{category_id}", response_model=DocCategoryOut)
def update_doc_category(
    category_id: int,
    payload: DocCategoryIn,
    request: Request,
    db: Session = Depends(get_db),
):
    ensure_doc_category_seed(db)
    row = db.get(DocumentCategoryDef, category_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document type not found")
    new_label = payload.label.strip()
    new_key = slug_category_key(payload.key or row.key)
    if new_key != row.key:
        if row.protected:
            raise HTTPException(status_code=400, detail="The fallback type cannot be renamed")
        clash = (
            db.query(DocumentCategoryDef)
            .filter(DocumentCategoryDef.key == new_key, DocumentCategoryDef.id != row.id)
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="That document type key already exists")
        reassign_documents(db, row.key, new_key)
        row.key = new_key
    row.label = new_label
    if payload.position is not None:
        row.position = payload.position
    row.active = payload.active
    if row.protected:
        row.active = True
    db.commit()
    db.refresh(row)
    notify_from_request(request, reason="doc-categories")
    return _doc_cat_out(row, db)


class StorageLocationIn(BaseModel):
    path: str = ""


@router.get("/storage")
def get_storage_locations(db: Session = Depends(get_db)):
    return describe_locations(db)


@router.put("/storage/{kind}")
def put_storage_location(kind: str, payload: StorageLocationIn, db: Session = Depends(get_db)):
    try:
        return upsert_location(db, kind, payload.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/doc-categories/{category_id}", status_code=204)
def delete_doc_category(category_id: int, request: Request, db: Session = Depends(get_db)):
    ensure_doc_category_seed(db)
    row = db.get(DocumentCategoryDef, category_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document type not found")
    if row.protected or row.key == FALLBACK_KEY:
        raise HTTPException(status_code=400, detail="The fallback type cannot be removed")
    reassign_documents(db, row.key, FALLBACK_KEY)
    row.active = False
    db.commit()
    notify_from_request(request, reason="doc-categories")

