from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from .models import WORKFLOW_STAGES, Site, WorkflowStep


def slugify_field_key(name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "custom_field"


def days_until(target: date | None, today: date | None = None) -> int | None:
    if target is None:
        return None
    today = today or date.today()
    return (target - today).days


def compute_today_priority(site: Site, threshold_days: int = 21) -> int:
    """Priority 1 when start date is within threshold_days; otherwise 2."""
    delta = days_until(site.indicative_site_start_date)
    if delta is None:
        return 2
    return 1 if delta < threshold_days else 2


def ensure_workflow_steps(site: Site) -> None:
    existing = {step.stage for step in site.workflow_steps}
    for stage in WORKFLOW_STAGES:
        if stage not in existing:
            site.workflow_steps.append(WorkflowStep(stage=stage, completed=False))


def apply_workflow(site: Site, workflow: dict[str, bool] | None) -> None:
    if not workflow:
        return
    ensure_workflow_steps(site)
    now = datetime.now(timezone.utc)
    by_stage = {step.stage: step for step in site.workflow_steps}
    for stage, completed in workflow.items():
        if stage not in by_stage:
            continue
        step = by_stage[stage]
        was_completed = step.completed
        step.completed = bool(completed)
        if step.completed and not was_completed:
            step.completed_at = now
        elif not step.completed:
            step.completed_at = None


def ordered_workflow(site: Site) -> list[WorkflowStep]:
    ensure_workflow_steps(site)
    order = {stage: idx for idx, stage in enumerate(WORKFLOW_STAGES)}
    return sorted(site.workflow_steps, key=lambda s: order.get(s.stage, 999))


def site_to_dict(site: Site) -> dict:
    workflow = ordered_workflow(site)
    return {
        "id": site.id,
        "road_name": site.road_name,
        "site_number": site.site_number,
        "indicative_site_start_date": site.indicative_site_start_date,
        "moa_must_have_received_date": site.moa_must_have_received_date,
        "comments": site.comments,
        "moa_number": site.moa_number,
        "moa_submission_date": site.moa_submission_date,
        "custom_fields": site.custom_fields or {},
        "today_priority": compute_today_priority(site),
        "workflow": [
            {
                "stage": step.stage,
                "completed": step.completed,
                "completed_at": step.completed_at,
                "note": step.note,
            }
            for step in workflow
        ],
        "document_count": len(site.documents or []),
        "tracking_count": len(site.tracking_events or []),
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def get_site_or_none(db: Session, site_id: int) -> Site | None:
    return db.get(Site, site_id)
