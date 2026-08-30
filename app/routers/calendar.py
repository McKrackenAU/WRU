"""Comms due-date calendar — visible to every signed-in user."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..comms_due import build_calendar_item
from ..database import get_db
from ..models import CommsRow, CommsTemplateField, Site, User

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


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
    items = []
    for row in rows:
        site = row.site if row.site_id else None
        if site is None and row.site_id:
            site = db.get(Site, row.site_id)
        for field in fields:
            item = build_calendar_item(field, row, site, today)
            if item:
                items.append(item)
    items.sort(key=lambda i: (i.get("due_date") or "9999-99-99", i.get("title") or ""))
    counts = {"completed": 0, "open": 0, "overdue": 0}
    for item in items:
        if item["status"] in counts:
            counts[item["status"]] += 1
    return {"items": items, "counts": counts, "today": today.isoformat()}
