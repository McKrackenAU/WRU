from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .calculations import compute_must_have_date, compute_today_priority, expand_workflow_prefix, site_metrics
from .financial_year import australian_financial_year
from .models import WORKFLOW_STAGES, Site, SiteCouncil, WorkflowStep
from .settings_store import get_rules
from .stage_registry import active_stages, stage_keys as registry_stage_keys

SITE_SCALAR_FIELDS = (
    "road_name",
    "site_number",
    "program",
    "tgs_reference",
    "indicative_site_start_date",
    "indicative_shifts_count",
    "moa_must_have_received_date",
    "must_have_manual",
    "priority_manual",
    "comments",
    "moa_number",
    "moa_submission_date",
    "moa_received_date",
    "moa_start_date",
    "moa_expiry_date",
    "extension_flag",
    "extension_submission_date",
    "extension_received_date",
    "extension_start_date",
    "extension_expiry_date",
    "job_completed_date",
    "include_in_totals",
    "is_generic_moa",
    "financial_year",
)


def slugify_field_key(name: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return key or "custom_field"


def indicative_shifts_count(site: Any, default: int = 1) -> int:
    """Gantt / cost work-shift count from a site's indicative planning field."""
    raw = getattr(site, "indicative_shifts_count", None) if site is not None else None
    if raw is None or raw == "":
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(365, n))


def _stage_context(db: Session | None) -> tuple[list[str], dict[str, str], set[str]]:
    if db is None:
        return (
            list(WORKFLOW_STAGES),
            {},
            {k for k in WORKFLOW_STAGES if k != "revision_needed"},
        )
    stages = active_stages(db)
    keys = [s.key for s in stages]
    roles = {s.key: s.list_role for s in stages}
    progress = {s.key for s in stages if s.counts_toward_progress}
    return keys, roles, progress


def ensure_workflow_steps(site: Site, db: Session | None = None) -> None:
    keys = registry_stage_keys(db) if db is not None else list(WORKFLOW_STAGES)
    existing = {step.stage for step in site.workflow_steps}
    for stage in keys:
        if stage not in existing:
            site.workflow_steps.append(WorkflowStep(stage=stage, completed=False))


def apply_workflow(site: Site, workflow: dict[str, bool] | None, db: Session | None = None) -> None:
    if not workflow:
        return
    ensure_workflow_steps(site, db)
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
        # Sync MoA received date when stage toggled
        if stage == "moa_received" and step.completed and not site.moa_received_date:
            site.moa_received_date = date.today()


def mark_ready_for_works(site: Site, db: Session | None = None) -> None:
    """Complete all progress stages through ready_for_works (generic MoA path)."""
    ensure_workflow_steps(site, db)
    keys, _roles, progress = _stage_context(db)
    now = datetime.now(timezone.utc)
    by_stage = {step.stage: step for step in site.workflow_steps}
    for key in keys:
        if key == "revision_needed":
            continue
        step = by_stage.get(key)
        if not step:
            continue
        if key in progress or key in ("moa_received", "ready_for_works"):
            if not step.completed:
                step.completed = True
                step.completed_at = now


def ordered_workflow(site: Site, db: Session | None = None) -> list[WorkflowStep]:
    ensure_workflow_steps(site, db)
    keys, _, _ = _stage_context(db)
    order = {stage: idx for idx, stage in enumerate(keys)}
    return sorted(site.workflow_steps, key=lambda s: order.get(s.stage, 999))


def set_councils(site: Site, councils: list[Any] | None) -> None:
    """Accept list[str] or list[{council_name, submitted_to_council_date, no_objection_date}].

    Updates the collection in place. Avoid clear()+re-add of the same council names —
    that can trip the unique (site_id, council_name) constraint mid-flush and break
    autosave with an opaque 500.
    """
    if councils is None:
        return
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in councils:
        if isinstance(raw, str):
            name = raw.strip()
            item = {
                "council_name": name,
                "submitted_to_council_date": None,
                "no_objection_date": None,
            }
        elif isinstance(raw, dict):
            name = (raw.get("council_name") or "").strip()
            item = {
                "council_name": name,
                "submitted_to_council_date": raw.get("submitted_to_council_date"),
                "no_objection_date": raw.get("no_objection_date"),
            }
        else:
            name = (getattr(raw, "council_name", None) or "").strip()
            item = {
                "council_name": name,
                "submitted_to_council_date": getattr(raw, "submitted_to_council_date", None),
                "no_objection_date": getattr(raw, "no_objection_date", None),
            }
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)

    existing = {c.council_name.lower(): c for c in list(site.councils or [])}
    keep: set[str] = set()
    for item in cleaned:
        key = item["council_name"].lower()
        keep.add(key)
        row = existing.get(key)
        if row is not None:
            row.submitted_to_council_date = item["submitted_to_council_date"]
            row.no_objection_date = item["no_objection_date"]
            # Preserve canonical casing from the form when it changes
            if row.council_name != item["council_name"]:
                row.council_name = item["council_name"]
        else:
            site.councils.append(
                SiteCouncil(
                    council_name=item["council_name"],
                    submitted_to_council_date=item["submitted_to_council_date"],
                    no_objection_date=item["no_objection_date"],
                )
            )
    for key, row in existing.items():
        if key not in keep:
            site.councils.remove(row)


def infer_financial_year(site: Site) -> str:
    if site.archived_fy:
        return site.archived_fy
    if site.financial_year:
        return site.financial_year
    anchor = (
        site.indicative_site_start_date
        or site.moa_submission_date
        or site.moa_must_have_received_date
        or site.moa_received_date
        or date.today()
    )
    return australian_financial_year(anchor)


def apply_generic_moa_link(site: Site, generic: Site | None, db: Session | None = None) -> None:
    if not generic:
        site.linked_generic_moa_id = None
        return
    if not generic.is_generic_moa:
        raise ValueError("Linked site is not marked as a generic MoA")
    site.linked_generic_moa_id = generic.id
    # Only fill blank identity fields — never overwrite another site's MoA number.
    if generic.moa_number and not (site.moa_number or "").strip():
        site.moa_number = generic.moa_number
    if generic.tgs_reference and not site.tgs_reference:
        site.tgs_reference = generic.tgs_reference
    mark_ready_for_works(site, db)


def sync_computed_fields(site: Site, db: Session | None = None) -> None:
    """Auto must-have date + archive-on-complete (spreadsheet AI=Yes behaviour)."""
    if db is not None:
        keys, _, _ = _stage_context(db)
        done = {step.stage: bool(step.completed) for step in site.workflow_steps}
        expanded = expand_workflow_prefix(done, keys)
        if any(expanded.get(key) != done.get(key, False) for key in expanded):
            apply_workflow(site, expanded, db)
    rules = get_rules(db)
    if rules.auto_compute_must_have and not site.must_have_manual:
        computed = compute_must_have_date(site, rules=rules)
        # Only set when not received; keep stored date for register display
        if computed is not None:
            site.moa_must_have_received_date = computed
    if site.job_completed_date and rules.auto_archive_on_job_complete and not site.archived:
        site.archived = True
        site.archived_at = datetime.now(timezone.utc)
        site.archived_fy = site.archived_fy or infer_financial_year(site)
        site.financial_year = site.financial_year or site.archived_fy


def site_to_dict(site: Site, *, include_metrics: bool = True, db: Session | None = None) -> dict:
    workflow = ordered_workflow(site, db)
    keys, roles, progress = _stage_context(db)
    rules = get_rules(db)
    metrics = (
        site_metrics(
            site,
            stage_keys=keys,
            list_roles=roles if roles else None,
            progress_keys=progress,
            rules=rules,
        )
        if include_metrics
        else {}
    )
    fy = infer_financial_year(site)
    council_details = [
        {
            "id": c.id,
            "council_name": c.council_name,
            "submitted_to_council_date": c.submitted_to_council_date,
            "no_objection_date": c.no_objection_date,
        }
        for c in (site.councils or [])
    ]
    return {
        "id": site.id,
        "road_name": site.road_name,
        "site_number": site.site_number,
        "program": site.program,
        "register_order": getattr(site, "register_order", None),
        "tgs_reference": site.tgs_reference,
        "indicative_site_start_date": site.indicative_site_start_date,
        "indicative_shifts_count": getattr(site, "indicative_shifts_count", None),
        "moa_must_have_received_date": site.moa_must_have_received_date,
        "must_have_manual": bool(getattr(site, "must_have_manual", False)),
        "priority_manual": getattr(site, "priority_manual", None),
        "comments": site.comments,
        "moa_number": site.moa_number,
        "moa_submission_date": site.moa_submission_date,
        "moa_received_date": getattr(site, "moa_received_date", None),
        "moa_start_date": getattr(site, "moa_start_date", None),
        "moa_expiry_date": getattr(site, "moa_expiry_date", None),
        "extension_flag": getattr(site, "extension_flag", None),
        "extension_submission_date": getattr(site, "extension_submission_date", None),
        "extension_received_date": getattr(site, "extension_received_date", None),
        "extension_start_date": getattr(site, "extension_start_date", None),
        "extension_expiry_date": getattr(site, "extension_expiry_date", None),
        "job_completed_date": getattr(site, "job_completed_date", None),
        "include_in_totals": bool(getattr(site, "include_in_totals", True)),
        "is_generic_moa": bool(getattr(site, "is_generic_moa", False)),
        "linked_generic_moa_id": getattr(site, "linked_generic_moa_id", None),
        "financial_year": fy,
        "archived": bool(site.archived),
        "archived_at": site.archived_at,
        "archived_fy": site.archived_fy,
        "councils": [c["council_name"] for c in council_details],
        "council_details": council_details,
        "custom_fields": site.custom_fields or {},
        "today_priority": metrics.get("today_priority", compute_today_priority(site, rules=rules)),
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
        "cost_estimate_count": len(site.cost_estimates or []),
        "latest_cost_total": _latest_cost_total(site),
        "created_at": site.created_at,
        "updated_at": site.updated_at,
    }


def _latest_cost_total(site: Site) -> float | None:
    estimates = list(site.cost_estimates or [])
    if not estimates:
        return None
    estimates.sort(key=lambda e: e.created_at or e.id, reverse=True)
    latest = estimates[0]
    if latest.summary_total is not None:
        return float(latest.summary_total)
    results = latest.results or {}
    if latest.mode == "standard":
        return results.get("site_traffic_total")
    a = (results.get("option_3x8") or {}).get("grand_total")
    b = (results.get("option_2x12") or {}).get("grand_total")
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


def get_site_or_none(db: Session, site_id: int) -> Site | None:
    return db.get(Site, site_id)
