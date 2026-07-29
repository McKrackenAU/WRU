from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from .calculations import compute_today_priority, site_metrics
from .financial_year import australian_financial_year
from .models import WORKFLOW_STAGES, Site, SiteCouncil, WorkflowStep


def slugify_field_key(name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "custom_field"


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


def set_councils(site: Site, councils: list[str] | None) -> None:
    if councils is None:
        return
    cleaned = []
    seen = set()
    for raw in councils:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    site.councils.clear()
    for name in cleaned:
        site.councils.append(SiteCouncil(council_name=name))


def infer_financial_year(site: Site) -> str:
    if site.archived_fy:
        return site.archived_fy
    if site.financial_year:
        return site.financial_year
    anchor = (
        site.indicative_site_start_date
        or site.moa_submission_date
        or site.moa_must_have_received_date
        or date.today()
    )
    return australian_financial_year(anchor)


def site_to_dict(site: Site, *, include_metrics: bool = True) -> dict:
    workflow = ordered_workflow(site)
    metrics = site_metrics(site) if include_metrics else {}
    fy = infer_financial_year(site)
    return {
        "id": site.id,
        "road_name": site.road_name,
        "site_number": site.site_number,
        "program": site.program,
        "tgs_reference": site.tgs_reference,
        "indicative_site_start_date": site.indicative_site_start_date,
        "moa_must_have_received_date": site.moa_must_have_received_date,
        "comments": site.comments,
        "moa_number": site.moa_number,
        "moa_submission_date": site.moa_submission_date,
        "financial_year": fy,
        "archived": bool(site.archived),
        "archived_at": site.archived_at,
        "archived_fy": site.archived_fy,
        "councils": [c.council_name for c in (site.councils or [])],
        "custom_fields": site.custom_fields or {},
        "today_priority": metrics.get("today_priority", compute_today_priority(site)),
        "metrics": metrics,
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
