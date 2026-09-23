from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import can_manage_comms, get_current_user
from ..calculations import must_have_status
from ..database import get_db
from ..models import ActualSpend, CommsRow, CostEstimate, Site, TrackingEvent, User
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


def _money_totals(db: Session, model, site_ids: set[int], kind=None) -> dict:
    if not site_ids:
        return {"estimated": 0, "sites_with_cost": 0}
    q = db.query(model).filter(model.site_id.in_(list(site_ids)))
    rows = q.all()
    latest: dict[int, float] = {}
    for row in rows:
        try:
            latest[int(row.site_id)] = float(row.summary_total or 0)
        except (TypeError, ValueError):
            continue
    return {
        "estimated": round(sum(latest.values()), 2),
        "sites_with_cost": len(latest),
    }


def _spend_totals(db: Session, site_ids: set[int]) -> dict:
    if not site_ids:
        return {"traffic": 0, "asphalt": 0, "total": 0}
    rows = db.query(ActualSpend).filter(ActualSpend.site_id.in_(list(site_ids))).all()
    traffic = 0.0
    asphalt = 0.0
    for row in rows:
        amt = float(row.amount or 0)
        if (row.kind or "") == "asphalt":
            asphalt += amt
        else:
            traffic += amt
    return {
        "traffic": round(traffic, 2),
        "asphalt": round(asphalt, 2),
        "total": round(traffic + asphalt, 2),
    }


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

    jobs = []

    def _add_job(site, data, *, archived: bool):
        metrics_stage = data["metrics"].get("current_stage") or "not_started"
        councils = [c.council_name for c in site.councils] or []
        band = must_have_status(site)["band"]
        jobs.append(
            {
                "id": site.id,
                "program": site.program or "",
                "stage": metrics_stage,
                "councils": councils,
                "priority": data.get("today_priority"),
                "must_have": band,
                "on_permits": bool(data["metrics"].get("on_permits_priority_list")),
                "on_trims": bool(data["metrics"].get("on_trims_priority_list")),
                "archived": archived,
                "documents": int(data.get("document_count") or 0),
                "estimated": float(data.get("latest_cost_total") or 0),
            }
        )
        return metrics_stage, councils, band

    for site, data in zip(sites, rows):
        metrics_stage, councils, band = _add_job(site, data, archived=False)
        stage_counts[metrics_stage] += 1
        for c in councils or ["(unassigned)"]:
            council_counts[c] += 1
        program_counts[site.program or "(no program)"] += 1
        priority_counts[data["today_priority"]] += 1
        must_counts[band] += 1
        if data["metrics"].get("on_permits_priority_list"):
            permits += 1
        if data["metrics"].get("on_trims_priority_list"):
            trims += 1

    archived_sites = lean_sites_query(db).filter(Site.archived.is_(True)).all()
    if archived_sites:
        for site, data in zip(archived_sites, serialize_sites(db, archived_sites)):
            _add_job(site, data, archived=True)

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
        "cost_totals": _money_totals(db, CostEstimate, focused_ids, kind=None),
        "spend_totals": _spend_totals(db, focused_ids),
        "jobs": jobs,
    }
