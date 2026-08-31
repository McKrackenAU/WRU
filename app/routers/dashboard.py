from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..calculations import must_have_status
from ..database import get_db
from ..models import Site, TrackingEvent
from ..schemas import DashboardOut
from ..services import lean_sites_query, serialize_sites
from ..stage_registry import active_stages

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    sites = lean_sites_query(db).filter(Site.archived.is_(False)).all()
    rows = serialize_sites(db, sites)
    archived_count = db.query(Site).filter(Site.archived.is_(True)).count()
    stages = active_stages(db)

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
        .limit(12)
        .all()
    )
    recent_tracking = []
    for ev in recent:
        recent_tracking.append(
            {
                "id": ev.id,
                "site_id": ev.site_id,
                "road_name": ev.site.road_name if ev.site else None,
                "site_number": ev.site.site_number if ev.site else None,
                "event_type": ev.event_type,
                "message": ev.message,
                "created_by": ev.created_by,
                "created_at": ev.created_at,
            }
        )

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
    }
