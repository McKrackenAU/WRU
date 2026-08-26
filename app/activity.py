"""Automatic activity / tracking events for multi-user audit trail."""

from __future__ import annotations

from sqlalchemy.orm import Session

from .calculations import current_stage_key
from .models import TrackingEvent, WORKFLOW_LABELS
from .stage_registry import stage_meta


def site_label(site) -> str:
    road = (getattr(site, "road_name", None) or "Unknown road").strip()
    number = (getattr(site, "site_number", None) or "").strip()
    return f"{road} - {number}" if number else road


def actor_name(request=None, *, fallback: str | None = None) -> str:
    if request is not None:
        name = (
            request.session.get("display_name")
            or request.session.get("username")
            or ""
        ).strip()
        if name:
            return name
    return (fallback or "Someone").strip() or "Someone"


def stage_label_for(db: Session, key: str | None) -> str:
    if not key:
        return "Not started"
    try:
        for row in stage_meta(db):
            if row.get("key") == key:
                return row.get("label") or WORKFLOW_LABELS.get(key, key)
    except Exception:
        pass
    return WORKFLOW_LABELS.get(key, key.replace("_", " ").title())


def log_site_activity(
    db: Session,
    site,
    *,
    message: str,
    event_type: str = "edit",
    created_by: str | None = None,
) -> TrackingEvent | None:
    text = (message or "").strip()
    if not text or site is None or not getattr(site, "id", None):
        return None
    event = TrackingEvent(
        site_id=site.id,
        event_type=(event_type or "edit").strip() or "edit",
        message=text[:4000],
        created_by=(created_by or "").strip() or None,
    )
    db.add(event)
    return event


def log_stage_change(
    db: Session,
    site,
    *,
    before_key: str | None,
    after_key: str | None,
    who: str,
) -> TrackingEvent | None:
    if before_key == after_key:
        return None
    before = stage_label_for(db, before_key)
    after = stage_label_for(db, after_key)
    return log_site_activity(
        db,
        site,
        event_type="status",
        created_by=who,
        message=f"{who} edited {site_label(site)}: {before} → {after}",
    )


def log_cost_added(
    db: Session,
    site,
    *,
    kind: str,
    who: str,
) -> TrackingEvent | None:
    label = "traffic costs" if kind == "traffic" else "pavement costs" if kind == "asphalt" else f"{kind} costs"
    return log_site_activity(
        db,
        site,
        event_type="cost",
        created_by=who,
        message=f"{who} edited {site_label(site)}, added {label}",
    )


def snapshot_stage(site, db: Session | None = None) -> str | None:
    keys = None
    if db is not None:
        try:
            keys = [s["key"] for s in stage_meta(db)]
        except Exception:
            keys = None
    return current_stage_key(site, keys)
