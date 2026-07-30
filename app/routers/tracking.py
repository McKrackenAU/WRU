from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Site, TrackingEvent
from ..schemas import TrackingEventCreate, TrackingEventOut

router = APIRouter(prefix="/api/sites/{site_id}/tracking", tags=["tracking"])


@router.get("", response_model=list[TrackingEventOut])
def list_tracking(site_id: int, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return (
        db.query(TrackingEvent)
        .filter(TrackingEvent.site_id == site_id)
        .order_by(TrackingEvent.created_at.desc(), TrackingEvent.id.desc())
        .all()
    )


@router.post("", response_model=TrackingEventOut, status_code=201)
def create_tracking(site_id: int, payload: TrackingEventCreate, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    event = TrackingEvent(
        site_id=site_id,
        event_type=payload.event_type.strip() or "note",
        message=payload.message.strip(),
        created_by=payload.created_by,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
def delete_tracking(site_id: int, event_id: int, db: Session = Depends(get_db)):
    event = (
        db.query(TrackingEvent)
        .filter(TrackingEvent.id == event_id, TrackingEvent.site_id == site_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Tracking event not found")
    db.delete(event)
    db.commit()
    return None
