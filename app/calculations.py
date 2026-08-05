"""Spreadsheet-style calculations for MoA workflow, client lists, and council waits.

Aligned to WRU Traffic TGS-MOA Tracker V6:
- Must-have = start − N business days (until MoA received → Received)
- Priority from must-have proximity (not site start)
- Council assumed no-objection after N business days
- MoA / extension wait SLA alerts
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .business_days import add_business_days, business_days_elapsed
from .models import WORKFLOW_STAGES, Site, WorkflowStep
from .settings_store import Rules

# Legacy module-level defaults (tests / callers without DB). Match spreadsheet V6.
PRIORITY_THRESHOLD_DAYS = 14
MUST_HAVE_OK_DAYS = 14
COUNCIL_NO_OBJECTION_BUSINESS_DAYS = 10
MUST_HAVE_OFFSET_BUSINESS_DAYS = 20
MOA_WAIT_SLA_BUSINESS_DAYS = 20

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


def _rules(rules: Rules | None = None) -> Rules:
    return rules or Rules()


def moa_is_received(site: Site, stage_keys: list[str] | None = None) -> bool:
    if getattr(site, "moa_received_date", None):
        return True
    keys = stage_keys or WORKFLOW_STAGES
    by_stage = {s.stage: s.completed for s in (site.workflow_steps or [])}
    for key in ("moa_received", "ready_for_works"):
        if key in keys and by_stage.get(key):
            return True
    return False


def compute_must_have_date(
    site: Site,
    *,
    rules: Rules | None = None,
) -> date | None:
    """Effective must-have date (None when MoA already received)."""
    r = _rules(rules)
    if moa_is_received(site):
        return None
    if site.moa_must_have_received_date and (
        getattr(site, "must_have_manual", False) or not r.auto_compute_must_have
    ):
        return site.moa_must_have_received_date
    if site.indicative_site_start_date and r.auto_compute_must_have:
        return add_business_days(
            site.indicative_site_start_date, -int(r.must_have_offset_business_days)
        )
    return site.moa_must_have_received_date


def compute_today_priority(
    site: Site,
    threshold_days: int | None = None,
    *,
    rules: Rules | None = None,
) -> int:
    """Priority 1 when must-have is within threshold days (or overdue); else 2.

    Spreadsheet: IF(must_have > TODAY()+14, 2, 1) — i.e. priority 1 when
    days_until(must_have) <= 14.
    """
    r = _rules(rules)
    thr = threshold_days if threshold_days is not None else r.priority_must_have_days
    if moa_is_received(site):
        return 2
    must = compute_must_have_date(site, rules=r)
    delta = days_until(must)
    if delta is None:
        # Fall back to start date if no must-have
        delta = days_until(site.indicative_site_start_date)
        if delta is None:
            return 2
    return 1 if delta <= thr else 2


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


def must_have_status(
    site: Site,
    today: date | None = None,
    *,
    rules: Rules | None = None,
) -> dict:
    r = _rules(rules)
    today = today or date.today()
    if moa_is_received(site):
        return {"band": "received", "days": None, "label": "Received", "date": None}
    must = compute_must_have_date(site, rules=r)
    delta = days_until(must, today)
    if delta is None:
        return {"band": "none", "days": None, "label": "—", "date": None}
    # Spreadsheet CF: green=Received; yellow within 7–14d past; red >7d past
    if delta < 0:
        overdue = abs(delta)
        if overdue > r.must_have_critical_days:
            band = "overdue"
        else:
            band = "warn"
        return {
            "band": band,
            "days": delta,
            "label": f"{overdue}d overdue",
            "date": must.isoformat(),
        }
    if delta <= r.must_have_warn_days:
        return {"band": "ok", "days": delta, "label": f"{delta}d", "date": must.isoformat()}
    return {"band": "late", "days": delta, "label": f"{delta}d", "date": must.isoformat()}


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
    """Return 'permits', 'trims', or 'none' for client export lists."""
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
    return client_list_bucket(site, stage_keys=stage_keys, list_roles=list_roles) == "permits"


def on_trims_priority_list(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
) -> bool:
    return client_list_bucket(site, stage_keys=stage_keys, list_roles=list_roles) == "trims"


def permits_priority_rank(site: Site, *, rules: Rules | None = None) -> int:
    pri = compute_today_priority(site, rules=rules)
    must = must_have_status(site, rules=rules)
    must_days = must["days"] if must["days"] is not None else 9999
    start_days = days_until(site.indicative_site_start_date)
    if start_days is None:
        start_days = 9999
    return pri * 10_000 + max(must_days, -999) * 10 + max(start_days, -999)


def _wait_metrics(
    submitted: date | None,
    received: date | None,
    today: date,
    *,
    sla_days: int,
) -> dict[str, Any]:
    end = received or today
    elapsed = business_days_elapsed(submitted, end) if submitted else None
    over_sla = bool(elapsed is not None and received is None and elapsed > sla_days)
    return {
        "submitted_date": submitted.isoformat() if submitted else None,
        "received_date": received.isoformat() if received else None,
        "business_days_waiting": elapsed,
        "over_sla": over_sla,
        "sla_days": sla_days,
        "status": (
            "received"
            if received
            else ("waiting" if submitted else "not_submitted")
        ),
    }


def moa_wait_metrics(
    site: Site,
    today: date | None = None,
    *,
    rules: Rules | None = None,
) -> dict[str, Any]:
    r = _rules(rules)
    today = today or date.today()
    received = getattr(site, "moa_received_date", None)
    return _wait_metrics(
        getattr(site, "moa_submission_date", None),
        received,
        today,
        sla_days=r.moa_wait_sla_business_days,
    )


def extension_wait_metrics(
    site: Site,
    today: date | None = None,
    *,
    rules: Rules | None = None,
) -> dict[str, Any]:
    r = _rules(rules)
    today = today or date.today()
    return _wait_metrics(
        getattr(site, "extension_submission_date", None),
        getattr(site, "extension_received_date", None),
        today,
        sla_days=r.moa_wait_sla_business_days,
    )


def validity_alert(
    expiry: date | None,
    today: date | None = None,
    *,
    rules: Rules | None = None,
) -> dict[str, Any]:
    r = _rules(rules)
    today = today or date.today()
    delta = days_until(expiry, today)
    if delta is None:
        return {"band": "none", "days": None, "label": "—"}
    if delta < 0:
        return {"band": "expired", "days": delta, "label": f"expired {abs(delta)}d"}
    if delta <= r.permit_validity_warn_days:
        return {"band": "critical", "days": delta, "label": f"{delta}d left"}
    if delta <= r.permit_validity_critical_days:
        return {"band": "warn", "days": delta, "label": f"{delta}d left"}
    return {"band": "ok", "days": delta, "label": f"{delta}d left"}


def council_wait_metrics(
    site: Site,
    today: date | None = None,
    *,
    rules: Rules | None = None,
    assume_days: int | None = None,
) -> list[dict[str, Any]]:
    """Per-council submit / no-objection / business-day wait tracking."""
    r = _rules(rules)
    today = today or date.today()
    days = assume_days if assume_days is not None else r.council_no_objection_business_days
    rows = []
    for council in site.councils or []:
        submitted = council.submitted_to_council_date
        no_obj = council.no_objection_date
        assumed_date = add_business_days(submitted, days) if submitted else None
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
                    "assumed_no_objection": f"Assumed no objection ({days} bus. days)",
                }.get(status, status),
            }
        )
    return rows


def max_council_business_days_waiting(
    site: Site, today: date | None = None, *, rules: Rules | None = None
) -> int | None:
    waits = [
        c["business_days_waiting"]
        for c in council_wait_metrics(site, today, rules=rules)
        if c["business_days_waiting"] is not None and c["status"] == "waiting"
    ]
    return max(waits) if waits else None


def site_metrics(
    site: Site,
    *,
    stage_keys: list[str] | None = None,
    list_roles: dict[str, str] | None = None,
    progress_keys: set[str] | None = None,
    rules: Rules | None = None,
) -> dict:
    r = _rules(rules)
    keys = stage_keys or WORKFLOW_STAGES
    roles = list_roles or _FALLBACK_LIST_ROLE
    bucket = client_list_bucket(site, stage_keys=keys, list_roles=roles)
    councils = council_wait_metrics(site, rules=r)
    must = must_have_status(site, rules=r)
    moa_wait = moa_wait_metrics(site, rules=r)
    ext_wait = extension_wait_metrics(site, rules=r)
    return {
        "today_priority": compute_today_priority(site, rules=r),
        "days_to_start": days_until(site.indicative_site_start_date),
        "start_status": start_status(site),
        "must_have_status": must,
        "must_have_date": must.get("date"),
        "workflow_progress_pct": workflow_progress_pct(
            site, stage_keys=keys, progress_keys=progress_keys
        ),
        "current_stage": current_stage_key(site, keys),
        "next_stage": next_stage_key(site, keys),
        "client_list": bucket,
        "on_permits_priority_list": bucket == "permits",
        "on_trims_priority_list": bucket == "trims",
        "permits_priority_rank": permits_priority_rank(site, rules=r),
        "stages_completed": sum(1 for s in _ordered_workflow(site, keys) if s.completed),
        "stages_total": len(keys),
        "councils": councils,
        "max_council_business_days_waiting": max_council_business_days_waiting(site, rules=r),
        "moa_wait": moa_wait,
        "extension_wait": ext_wait,
        "moa_validity": validity_alert(getattr(site, "moa_expiry_date", None), rules=r),
        "extension_validity": validity_alert(
            getattr(site, "extension_expiry_date", None), rules=r
        ),
        "moa_received": moa_is_received(site, keys),
    }
