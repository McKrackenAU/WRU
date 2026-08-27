"""Global activity feed API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Site, TrackingEvent

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("")
def list_activity(
    request: Request,
    q: str | None = Query(default=None),
    program: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    mine: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = (
        db.query(TrackingEvent)
        .options(joinedload(TrackingEvent.site))
        .join(Site)
        .order_by(TrackingEvent.created_at.desc(), TrackingEvent.id.desc())
    )
    if not include_archived:
        query = query.filter(Site.archived.is_(False))
    if program and program.strip():
        query = query.filter(Site.program == program.strip())
    if event_type and event_type.strip():
        query = query.filter(TrackingEvent.event_type == event_type.strip())
    if mine:
        names = {
            (request.session.get("display_name") or "").strip(),
            (request.session.get("username") or "").strip(),
        }
        names.discard("")
        if names:
            query = query.filter(TrackingEvent.created_by.in_(names))
        else:
            query = query.filter(TrackingEvent.id == -1)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                TrackingEvent.message.ilike(like),
                TrackingEvent.created_by.ilike(like),
                Site.road_name.ilike(like),
                Site.site_number.ilike(like),
                Site.moa_number.ilike(like),
            )
        )
    rows = query.limit(limit).all()
    out = []
    for ev in rows:
        site = ev.site
        out.append(
            {
                "id": ev.id,
                "site_id": ev.site_id,
                "road_name": site.road_name if site else None,
                "site_number": site.site_number if site else None,
                "program": site.program if site else None,
                "event_type": ev.event_type,
                "message": ev.message,
                "created_by": ev.created_by,
                "created_at": ev.created_at,
                "archived": bool(site.archived) if site else False,
            }
        )
    return out
