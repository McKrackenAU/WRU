"""Spreadsheet-style calculations ported from the LCP-FMRP MoA tracker sheet.

Derived from the visible workbook rules (priority, must-have bands, TRIMS
permits priority list). Original VBA was not available in-repo; these match
the sheet headers/legends described for that workbook.
"""

from __future__ import annotations

from datetime import date

from .models import WORKFLOW_STAGES, Site, WorkflowStep

PRIORITY_THRESHOLD_DAYS = 21
MUST_HAVE_OK_DAYS = 14


def days_until(target: date | None, today: date | None = None) -> int | None:
    if target is None:
        return None
    today = today or date.today()
    return (target - today).days


def compute_today_priority(site: Site, threshold_days: int = PRIORITY_THRESHOLD_DAYS) -> int:
    delta = days_until(site.indicative_site_start_date)
    if delta is None:
        return 2
    return 1 if delta < threshold_days else 2


def _ordered_workflow(site: Site) -> list[WorkflowStep]:
    existing = {step.stage: step for step in (site.workflow_steps or [])}
    # Don't mutate here during read-only metrics; just order what exists
    steps = list(existing.values())
    order = {stage: idx for idx, stage in enumerate(WORKFLOW_STAGES)}
    return sorted(steps, key=lambda s: order.get(s.stage, 999))


def current_stage_key(site: Site) -> str | None:
    steps = _ordered_workflow(site)
    last_done = None
    first_open = None
    for step in steps:
        if step.completed:
            last_done = step.stage
        elif first_open is None:
            first_open = step.stage
    return last_done or first_open


def next_stage_key(site: Site) -> str | None:
    for step in _ordered_workflow(site):
        if not step.completed:
            return step.stage
    return None


def workflow_progress_pct(site: Site) -> int:
    steps = _ordered_workflow(site)
    if not steps:
        return 0
    linear = [s for s in steps if s.stage != "revision_needed"]
    if not linear:
        return 0
    done = sum(1 for s in linear if s.completed)
    return round(100 * done / len(linear))


def must_have_status(site: Site, today: date | None = None) -> dict:
    """Legend from sheet: green 0–14 days, red 14+ days (or overdue)."""
    delta = days_until(site.moa_must_have_received_date, today)
    if delta is None:
        return {"band": "none", "days": None, "label": "—"}
    if delta < 0:
        return {"band": "overdue", "days": delta, "label": f"{abs(delta)}d overdue"}
    if delta <= MUST_HAVE_OK_DAYS:
        return {"band": "ok", "days": delta, "label": f"{delta}d"}
    return {"band": "late", "days": delta, "label": f"{delta}d"}


def start_status(site: Site, today: date | None = None) -> dict:
    delta = days_until(site.indicative_site_start_date, today)
    if delta is None:
        return {"days": None, "label": "—"}
    if delta < 0:
        return {"days": delta, "label": f"{abs(delta)}d ago"}
    return {"days": delta, "label": f"{delta}d"}


def on_permits_priority_list(site: Site) -> bool:
    """Sites that still need client/TRIMS attention.

    Sheet column: MoA 'WITH TRIMS' — (Remove from Permits Priority List).
    """
    by_stage = {s.stage: s.completed for s in _ordered_workflow(site)}
    if by_stage.get("ready_for_works") or by_stage.get("moa_received"):
        return False
    if by_stage.get("moa_with_trims") and not by_stage.get("revision_needed"):
        return False
    return bool(
        by_stage.get("ready_to_submit_moa")
        or by_stage.get("moa_submitted")
        or by_stage.get("revision_needed")
    )


def permits_priority_rank(site: Site) -> int:
    pri = compute_today_priority(site)
    must = must_have_status(site)
    must_days = must["days"] if must["days"] is not None else 9999
    start_days = days_until(site.indicative_site_start_date)
    if start_days is None:
        start_days = 9999
    return pri * 10_000 + max(must_days, -999) * 10 + max(start_days, -999)


def site_metrics(site: Site) -> dict:
    return {
        "today_priority": compute_today_priority(site),
        "days_to_start": days_until(site.indicative_site_start_date),
        "start_status": start_status(site),
        "must_have_status": must_have_status(site),
        "workflow_progress_pct": workflow_progress_pct(site),
        "current_stage": current_stage_key(site),
        "next_stage": next_stage_key(site),
        "on_permits_priority_list": on_permits_priority_list(site),
        "permits_priority_rank": permits_priority_rank(site),
        "stages_completed": sum(1 for s in _ordered_workflow(site) if s.completed),
        "stages_total": len(WORKFLOW_STAGES),
    }
