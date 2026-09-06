from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import can_manage_comms, get_current_user
from ..calculations import must_have_status
from ..database import get_db
from ..models import CommsRow, Site, TrackingEvent, User
from ..notify import (
    category_tags_for_program,
    effective_job_tags,
    site_matches_user_focus,
    user_tag_set,
)
from ..schemas import DashboardOut
from ..services import lean_sites_query, serialize_sites
from ..stage_registry import active_stages

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sites = lean_sites_query(db).filter(Site.archived.is_(False)).all()
    rows = serialize_sites(db, sites)
    archived_count = db.query(Site).filter(Site.archived.is_(True)).count()
    stages = active_stages(db)
    focus_tags = sorted(user_tag_set(user))
    focused = [site for site in sites if site_matches_user_focus(site, user, db)]
    focused_ids = {site.id for site in focused}

    stage_counts = Counter()
    council_counts = Counter()
    program_counts = Counter()
    priority_counts = Counter()
    must_counts = Counter()
    permits = 0
    trims = 0

    for site, data in zip(sites, rows):
        metrics_stage = data["metrics"].get("current_stage") or "not_started"
        stage_counts[metrics_stage] += 1

        councils = [c.council_name for c in site.councils] or ["(unassigned)"]
        for c in councils:
            council_counts[c] += 1

        program_counts[site.program or "(no program)"] += 1
        priority_counts[data["today_priority"]] += 1
        must_counts[must_have_status(site)["band"]] += 1
        if data["metrics"].get("on_permits_priority_list"):
            permits += 1
        if data["metrics"].get("on_trims_priority_list"):
            trims += 1

    by_stage = [
        {
            "key": s.key,
            "label": s.label,
            "count": stage_counts.get(s.key, 0),
        }
        for s in stages
    ]
    by_stage.insert(
        0,
        {"key": "not_started", "label": "Not started", "count": stage_counts.get("not_started", 0)},
    )

    recent = (
        db.query(TrackingEvent)
        .join(Site)
        .filter(Site.archived.is_(False))
        .order_by(TrackingEvent.created_at.desc())
        .limit(40)
        .all()
    )
    recent_tracking = []
    recent_status_changes = []
    for ev in recent:
        item = {
            "id": ev.id,
            "site_id": ev.site_id,
            "road_name": ev.site.road_name if ev.site else None,
            "site_number": ev.site.site_number if ev.site else None,
            "event_type": ev.event_type,
            "message": ev.message,
            "created_by": ev.created_by,
            "created_at": ev.created_at,
        }
        if len(recent_tracking) < 12:
            recent_tracking.append(item)
        if ev.site_id in focused_ids and len(recent_status_changes) < 8:
            recent_status_changes.append(item)

    recent_approvals = []
    for site in sorted(
        [s for s in focused if s.moa_received_date],
        key=lambda s: (s.moa_received_date, s.id),
        reverse=True,
    )[:8]:
        recent_approvals.append(
            {
                "id": site.id,
                "site_number": site.site_number,
                "road_name": site.road_name,
                "program": site.program,
                "moa_number": site.moa_number,
                "moa_received_date": _iso(site.moa_received_date),
                "tags": effective_job_tags(site, category_tags_for_program(db, site.program)),
            }
        )

    comms_preview = []
    show_comms = can_manage_comms(user) or "comms" in user_tag_set(user)
    if show_comms:
        comms_rows = (
            db.query(CommsRow)
            .order_by(CommsRow.updated_at.desc(), CommsRow.id.desc())
            .limit(40)
            .all()
        )
        for row in comms_rows:
            linked = row.site
            if linked is not None and linked.id not in focused_ids:
                continue
            if linked is None and focus_tags and "comms" not in focus_tags and not can_manage_comms(user):
                continue
            comms_preview.append(
                {
                    "id": row.id,
                    "section": row.section,
                    "site_id": row.site_id,
                    "site_number": linked.site_number if linked else None,
                    "road_name": linked.road_name if linked else None,
                    "updated_at": _iso(row.updated_at),
                }
            )
            if len(comms_preview) >= 8:
                break

    return {
        "totals": {
            "active_sites": len(sites),
            "archived_sites": archived_count,
            "documents": sum(int(r.get("document_count") or 0) for r in rows),
            "tracking_events": sum(int(r.get("tracking_count") or 0) for r in rows),
        },
        "by_stage": by_stage,
        "by_council": [
            {"name": name, "count": count}
            for name, count in sorted(council_counts.items(), key=lambda x: (-x[1], x[0]))
        ],
        "by_program": [
            {"name": name, "count": count}
            for name, count in sorted(program_counts.items(), key=lambda x: (-x[1], x[0]))
        ],
        "priority": {
            "priority_1": priority_counts.get(1, 0),
            "priority_2": priority_counts.get(2, 0),
        },
        "must_have": {
            "ok": must_counts.get("ok", 0),
            "late": must_counts.get("late", 0),
            "overdue": must_counts.get("overdue", 0),
            "none": must_counts.get("none", 0),
        },
        "permits_priority_count": permits,
        "trims_priority_count": trims,
        "recent_tracking": recent_tracking,
        "focus_tags": focus_tags,
        "recent_approvals": recent_approvals,
        "recent_status_changes": recent_status_changes,
        "comms_preview": comms_preview,
    }
