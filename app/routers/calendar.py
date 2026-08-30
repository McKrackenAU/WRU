"""Comms due-date calendar — visible to every signed-in user."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..activity import actor_name
from ..auth import get_current_user
from ..comms_due import build_calendar_item
from ..database import get_db
from ..models import CalendarItemNote, CommsRow, CommsTemplateField, Site, User
from ..notify import (
    dispatch_calendar_note_notifications,
    effective_job_tags,
    program_tag_map,
)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CalendarNoteIn(BaseModel):
    row_id: int
    field_key: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=4000)


def _note_to_public(note: CalendarItemNote) -> dict:
    return {
        "id": note.id,
        "row_id": note.row_id,
        "field_key": note.field_key,
        "body": note.body,
        "created_by": note.created_by,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


def _resolve_field(db: Session, field_key: str) -> CommsTemplateField:
    field = (
        db.query(CommsTemplateField)
        .filter(CommsTemplateField.field_key == field_key.strip())
        .first()
    )
    if not field:
        raise HTTPException(status_code=404, detail="Calendar field not found")
    if not field.track_due:
        raise HTTPException(status_code=400, detail="That field is not on the calendar")
    return field


@router.get("/comms")
def comms_calendar(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    fields = (
        db.query(CommsTemplateField)
        .filter(CommsTemplateField.track_due.is_(True))
        .order_by(CommsTemplateField.position.asc(), CommsTemplateField.id.asc())
        .all()
    )
    if not fields:
        return {"items": [], "counts": {"completed": 0, "open": 0, "overdue": 0}}
    rows = db.query(CommsRow).order_by(CommsRow.id.asc()).all()
    today = date.today()
    counts_by_item: dict[tuple[int, str], int] = defaultdict(int)
    if rows:
        for row_id, field_key, n in (
            db.query(CalendarItemNote.row_id, CalendarItemNote.field_key, func.count())
            .group_by(CalendarItemNote.row_id, CalendarItemNote.field_key)
            .all()
        ):
            counts_by_item[(int(row_id), str(field_key))] = int(n)
    cat_map = program_tag_map(db)
    items = []
    for row in rows:
        site = row.site if row.site_id else None
        if site is None and row.site_id:
            site = db.get(Site, row.site_id)
        program = (getattr(site, "program", None) or "").strip() if site else ""
        inherited = cat_map.get(program.lower(), []) if program else []
        job_tags = effective_job_tags(site, inherited) if site is not None else list(inherited)
        for field in fields:
            item = build_calendar_item(field, row, site, today)
            if not item:
                continue
            item["tags"] = job_tags
            item["category_tags"] = inherited
            item["job_tags"] = list(getattr(site, "tags", None) or []) if site is not None else []
            item["note_count"] = counts_by_item.get((int(row.id), field.field_key), 0)
            items.append(item)
    items.sort(key=lambda i: (i.get("due_date") or "9999-99-99", i.get("title") or ""))
    counts = {"completed": 0, "open": 0, "overdue": 0}
    for item in items:
        if item["status"] in counts:
            counts[item["status"]] += 1
    return {"items": items, "counts": counts, "today": today.isoformat()}


@router.get("/comms/notes")
def list_calendar_notes(
    row_id: int = Query(...),
    field_key: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _resolve_field(db, field_key)
    row = db.get(CommsRow, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Comms row not found")
    notes = (
        db.query(CalendarItemNote)
        .filter(CalendarItemNote.row_id == row_id, CalendarItemNote.field_key == field_key.strip())
        .order_by(CalendarItemNote.created_at.asc(), CalendarItemNote.id.asc())
        .all()
    )
    return {"items": [_note_to_public(n) for n in notes]}


@router.post("/comms/notes", status_code=201)
def add_calendar_note(
    payload: CalendarNoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    field = _resolve_field(db, payload.field_key)
    row = db.get(CommsRow, payload.row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Comms row not found")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    who = actor_name(request) or (user.display_name or user.username)
    note = CalendarItemNote(
        row_id=row.id,
        field_key=field.field_key,
        body=body[:4000],
        created_by=who,
    )
    db.add(note)
    db.flush()
    site = row.site if row.site_id else None
    if site is None and row.site_id:
        site = db.get(Site, row.site_id)
    dispatch_calendar_note_notifications(db, note=note, row=row, field=field, site=site, author=user)
    db.commit()
    db.refresh(note)
    return _note_to_public(note)
