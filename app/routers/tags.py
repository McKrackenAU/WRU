"""Tag library: public list for pickers, admin CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import ProgramCategory, TagDef, User
from ..notify import (
    ensure_tag_seed,
    normalize_tags,
    pretty_tag_label,
    retarget_tag_slug,
    tag_to_public,
)

public_router = APIRouter(prefix="/api/tags", tags=["tags"])
admin_router = APIRouter(
    prefix="/api/admin/tags",
    tags=["admin-tags"],
    dependencies=[Depends(require_admin)],
)


class TagIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    slug: str | None = Field(default=None, max_length=32)
    position: int | None = None


class TagPatchIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    slug: str | None = Field(default=None, max_length=32)
    position: int | None = None


def _slug_from(label: str, slug: str | None) -> str:
    parts = normalize_tags(slug or label)
    if not parts:
        raise HTTPException(status_code=400, detail="Tag name is empty after cleaning")
    return parts[0]


@public_router.get("")
def list_tags_public(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ensure_tag_seed(db)
    rows = db.query(TagDef).order_by(TagDef.position.asc(), TagDef.id.asc()).all()
    return {
        "items": [tag_to_public(row) for row in rows],
        "program_tags": {
            (row.name or "").strip(): normalize_tags(getattr(row, "tags", None))
            for row in db.query(ProgramCategory).all()
            if (row.name or "").strip()
        },
    }


@admin_router.get("")
def list_tags_admin(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    ensure_tag_seed(db)
    rows = db.query(TagDef).order_by(TagDef.position.asc(), TagDef.id.asc()).all()
    return [tag_to_public(row) for row in rows]


@admin_router.post("", status_code=201)
def create_tag(payload: TagIn, db: Session = Depends(get_db)):
    ensure_tag_seed(db)
    slug = _slug_from(payload.label, payload.slug)
    if db.query(TagDef).filter(TagDef.slug == slug).first():
        raise HTTPException(status_code=400, detail="That tag already exists")
    max_pos = db.query(func.max(TagDef.position)).scalar() or 0
    label = (payload.label or "").strip() or pretty_tag_label(slug)
    row = TagDef(
        slug=slug,
        label=label[:64],
        position=payload.position if payload.position is not None else max_pos + 10,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return tag_to_public(row)


@admin_router.patch("/{tag_id}")
def update_tag(tag_id: int, payload: TagPatchIn, db: Session = Depends(get_db)):
    row = db.get(TagDef, tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    old_slug = row.slug
    if payload.label is not None:
        row.label = payload.label.strip()[:64] or pretty_tag_label(row.slug)
    if payload.slug is not None:
        new_slug = _slug_from(payload.label or row.label, payload.slug)
        clash = db.query(TagDef).filter(TagDef.slug == new_slug, TagDef.id != tag_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="That tag already exists")
        row.slug = new_slug
        if payload.label is None:
            row.label = pretty_tag_label(new_slug)
    if payload.position is not None:
        row.position = payload.position
    if row.slug != old_slug:
        retarget_tag_slug(db, old_slug, row.slug)
    db.commit()
    db.refresh(row)
    return tag_to_public(row)


@admin_router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    row = db.get(TagDef, tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(row)
    db.commit()
    return None
