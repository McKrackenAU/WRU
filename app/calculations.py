"""Spreadsheet-style calculations for MoA workflow, client lists, and council waits."""

from __future__ import annotations

from datetime import date
from typing import Any

from .business_days import add_business_days, business_days_elapsed
from .models import WORKFLOW_STAGES, Site, WorkflowStep

PRIORITY_THRESHOLD_DAYS = 21
MUST_HAVE_OK_DAYS = 14
COUNCIL_NO_OBJECTION_BUSINESS_DAYS = 21

# Fallback list roles when DB stage defs are not injected
_FALLBACK_LIST_ROLE = {
    "tgs_markup_completed": "none",
    "submitted_to_tmd": "none",
    "ventia_review": "none",
    "plan_received": "none",
    "ready_to_submit_moa": "none",
    "moa_submitted": "permits",
    "moa_with_trims": "trims",
    "revision_needed": "permits",
    "moa_received": "complete",
    "ready_for_works": "complete",
}


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


def _stage_order(stage_keys: list[str] | None) -> dict[str, int]:
    keys = stage_keys or WORKFLOW_STAGES
    return {stage: idx for idx, stage in enumerate(keys)}


def _ordered_workflow(site: Site, stage_keys: list[str] | None = None) -> list[WorkflowStep]:
    existing = {step.stage: step for step in (site.workflow_steps or [])}
    steps = list(existing.values())
    order = _stage_order(stage_keys)
    return sorted(steps, key=lambda s: order.get(s.stage, 999))


def current_stage_key(site: Site, stage_keys: list[str] | None = None) -> str | None:
    steps = _ordered_workflow(site, stage_keys)
    last_done = None
    first_open = None
    for step in steps:
        if step.completed:
            last_done = step.stage
        elif first_open is None:
            first_open = step.stage
    return last_done or first_open


def next_stage_key(site: Site, stage_keys: list[str] | None = None) -> str | None:
    for step in _ordered_workflow(site, stage_keys):
        if not step.completed:
            return step.stage
    return None


def workflow_progress_pct(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    progress_keys: set[str] | None = None,
) -> int:
    steps = _ordered_workflow(site, stage_keys)
    if not steps:
        return 0
    if progress_keys is None:
        linear = [s for s in steps if s.stage != "revision_needed"]
    else:
        linear = [s for s in steps if s.stage in progress_keys]
    if not linear:
        return 0
    done = sum(1 for s in linear if s.completed)
    return round(100 * done / len(linear))


def must_have_status(site: Site, today: date | None = None) -> dict:
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


def client_list_bucket(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
) -> str:
    """Return 'permits', 'trims', or 'none' for client export lists.

    Uses the furthest completed stage that has a non-none list_role:
    - none → not on either client list (pre-DTP, or no list-role stages done)
    - permits / trims → exclusive team list (later stage wins, e.g. TRIMS after Permits;
      revision with list_role=permits pulls back from TRIMS)
    - complete → removed from both (approved / received / ready for works)
    """
    roles = list_roles or _FALLBACK_LIST_ROLE
    by_stage = {s.stage: s.completed for s in _ordered_workflow(site, stage_keys)}

    furthest_role = "none"
    for key in stage_keys or WORKFLOW_STAGES:
        if not by_stage.get(key):
            continue
        role = roles.get(key, "none")
        if role != "none":
            furthest_role = role

    if furthest_role == "complete":
        return "none"
    if furthest_role in ("permits", "trims"):
        return furthest_role
    return "none"


def on_permits_priority_list(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
) -> bool:
    return (
        client_list_bucket(site, stage_keys=stage_keys, list_roles=list_roles) == "permits"
    )


def on_trims_priority_list(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
) -> bool:
    return client_list_bucket(site, stage_keys=stage_keys, list_roles=list_roles) == "trims"


def permits_priority_rank(site: Site) -> int:
    pri = compute_today_priority(site)
    must = must_have_status(site)
    must_days = must["days"] if must["days"] is not None else 9999
    start_days = days_until(site.indicative_site_start_date)
    if start_days is None:
        start_days = 9999
    return pri * 10_000 + max(must_days, -999) * 10 + max(start_days, -999)


def council_wait_metrics(site: Site, today: date | None = None) -> list[dict[str, Any]]:
    """Per-council submit / no-objection / business-day wait tracking."""
    today = today or date.today()
    rows = []
    for council in site.councils or []:
        submitted = council.submitted_to_council_date
        no_obj = council.no_objection_date
        assumed_date = (
            add_business_days(submitted, COUNCIL_NO_OBJECTION_BUSINESS_DAYS)
            if submitted
            else None
        )
        elapsed = business_days_elapsed(submitted, today) if submitted else None
        assumed = False
        effective_no_obj = no_obj
        if submitted and no_obj is None and assumed_date and today >= assumed_date:
            assumed = True
            effective_no_obj = assumed_date
        status = "not_submitted"
        if effective_no_obj:
            status = "assumed_no_objection" if assumed else "no_objection"
        elif submitted:
            status = "waiting"
        rows.append(
            {
                "council_name": council.council_name,
                "submitted_to_council_date": submitted.isoformat() if submitted else None,
                "no_objection_date": no_obj.isoformat() if no_obj else None,
                "assumed_no_objection_date": assumed_date.isoformat() if assumed_date else None,
                "assumed_no_objection": assumed,
                "business_days_waiting": elapsed,
                "status": status,
                "status_label": {
                    "not_submitted": "Not submitted",
                    "waiting": f"Waiting ({elapsed} bus. days)" if elapsed is not None else "Waiting",
                    "no_objection": "No objection",
                    "assumed_no_objection": f"Assumed no objection ({COUNCIL_NO_OBJECTION_BUSINESS_DAYS} bus. days)",
                }.get(status, status),
            }
        )
    return rows


def max_council_business_days_waiting(site: Site, today: date | None = None) -> int | None:
    waits = [
        c["business_days_waiting"]
        for c in council_wait_metrics(site, today)
        if c["business_days_waiting"] is not None and c["status"] == "waiting"
    ]
    return max(waits) if waits else None


def site_metrics(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
    progress_keys: set[str] | None = None,
) -> dict:
    keys = stage_keys or WORKFLOW_STAGES
    roles = list_roles or _FALLBACK_LIST_ROLE
    bucket = client_list_bucket(site, stage_keys=keys, list_roles=roles)
    councils = council_wait_metrics(site)
    return {
        "today_priority": compute_today_priority(site),
        "days_to_start": days_until(site.indicative_site_start_date),
        "start_status": start_status(site),
        "must_have_status": must_have_status(site),
        "workflow_progress_pct": workflow_progress_pct(
            site, stage_keys=keys, progress_keys=progress_keys
        ),
        "current_stage": current_stage_key(site, keys),
        "next_stage": next_stage_key(site, keys),
        "client_list": bucket,
        "on_permits_priority_list": bucket == "permits",
        "on_trims_priority_list": bucket == "trims",
        "permits_priority_rank": permits_priority_rank(site),
        "stages_completed": sum(1 for s in _ordered_workflow(site, keys) if s.completed),
        "stages_total": len(keys),
        "councils": councils,
        "max_council_business_days_waiting": max_council_business_days_waiting(site),
    }
