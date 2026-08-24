"""Import sites from WRU Traffic TGS-MOA Tracker Excel (.xlsx / .xlsm)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from .models import Site
from .services import apply_workflow, ensure_workflow_steps, set_councils, sync_computed_fields
from .stage_registry import active_programs

# Spreadsheet status text → cumulative completed stages
STATUS_STAGES: dict[str, list[str]] = {
    "not yet started": [],
    "tgs markup complete": ["tgs_markup_completed"],
    "submitted to tmd": ["tgs_markup_completed", "submitted_to_tmd"],
    "plan received": ["tgs_markup_completed", "submitted_to_tmd", "plan_received"],
    "ready to submit moa": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
    ],
    "moa submitted": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
    ],
    "moa with trims": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
        "moa_with_trims",
    ],
    "revision needed": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
        "moa_with_trims",
        "revision_needed",
    ],
    "moa received": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
        "moa_with_trims",
        "moa_received",
    ],
    "ready for works": [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
        "moa_with_trims",
        "moa_received",
        "ready_for_works",
    ],
}

# Spreadsheet dropdown / formula casing variants → canonical STATUS_STAGES key
STATUS_ALIASES: dict[str, str] = {
    "not yet started": "not yet started",
    "not started": "not yet started",
    "tgs markup completed": "tgs markup complete",
    "tgs markup complete": "tgs markup complete",
    "submitted to tmd": "submitted to tmd",
    "submitted to tm": "submitted to tmd",
    "submitted to traffic management": "submitted to tmd",
    "submitted to traffic management designer": "submitted to tmd",
    "plan received": "plan received",
    "ready to submit moa": "ready to submit moa",
    "ready for submit moa": "ready to submit moa",
    "moa submitted": "moa submitted",
    "moa with trims": "moa with trims",
    'moa "with trims"': "moa with trims",
    "moa with trims - (remove from permits priority list)": "moa with trims",
    "revision needed": "revision needed",
    "revision required": "revision needed",
    "moa received": "moa received",
    "ready for works": "ready for works",
    "ready to works": "ready for works",
    "ventia review": "plan received",
}

# Back-compat name used by tests / callers
STATUS_MAP: list[tuple[str, list[str]]] = [(k, v) for k, v in STATUS_STAGES.items()]

# Column A section headers in the V6 workbook
SECTION_HINTS = [
    ("lcp - fmrp", "LCP-FMRP"),
    ("lcp-fmrp", "LCP-FMRP"),
    ("fmrp non", "FMRP Non-Commit"),
    ("maintenace", "LCP Maintenance Misc"),  # typo in sheet
    ("maintenance", "LCP Maintenance Misc"),
    ("structure", "Structures"),
    ("generic", "Generics MTMP/ITMP"),
    ("routine", "Routine Maintenance"),
]

SKIP_ROAD = {
    "road name",
    "add new line above",
    "totals",
    "jobs",
    "none",
    "",
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        # Excel sometimes stores small serials as datetime near 1900
        if value.year < 1950:
            return None
        return value.date()
    if isinstance(value, date):
        return value
    text = _norm(value)
    if not text or text.lower() in ("received", "n/a", "na", "-", "yes", "no"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        n = float(value)
        if 20000 < n < 80000:
            return (datetime(1899, 12, 30) + timedelta(days=int(n))).date()
    except (TypeError, ValueError):
        pass
    return None


def _status_workflow(status: str) -> tuple[dict[str, bool], str | None]:
    """Return (workflow flags, unmatched original text if we fell back)."""
    key = _norm(status).lower()
    unmatched: str | None = None
    if not key or key in ("n/a", "na", "-", "0"):
        key = "not yet started"
    elif key in ("yes", "y"):
        # Structures / generics Yes-No lamps
        key = "ready for works"
    elif key in ("no", "n"):
        key = "not yet started"
    elif key.isdigit():
        key = "not yet started"
        unmatched = status
    else:
        canonical = STATUS_ALIASES.get(key)
        if canonical is None:
            for alias, target in STATUS_ALIASES.items():
                if alias in key or key in alias:
                    canonical = target
                    break
        if canonical is None:
            unmatched = status
            key = "not yet started"
        else:
            key = canonical
    stages = STATUS_STAGES.get(key, [])
    all_keys = [
        "tgs_markup_completed",
        "submitted_to_tmd",
        "plan_received",
        "ready_to_submit_moa",
        "moa_submitted",
        "moa_with_trims",
        "revision_needed",
        "moa_received",
        "ready_for_works",
    ]
    return {k: k in stages for k in all_keys}, unmatched


def _section_from_a(value: Any) -> str | None:
    text = _norm(value).lower()
    if not text:
        return None
    for hint, name in SECTION_HINTS:
        if hint in text:
            return name
    return None


def _find_tracker_sheet(wb):
    for name in wb.sheetnames:
        if "tgs" in name.lower() and "moa" in name.lower():
            return wb[name]
    for name in wb.sheetnames:
        if "enable" in name.lower() or "dashboard" in name.lower():
            continue
        return wb[name]
    return wb[wb.sheetnames[0]]


def parse_tracker_workbook(content: bytes) -> dict[str, Any]:
    wb = load_workbook(BytesIO(content), data_only=True, read_only=True)
    ws = _find_tracker_sheet(wb)
    rows_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unmatched_statuses: list[str] = []
    current_program = "LCP-FMRP"

    for r in range(1, (ws.max_row or 0) + 1):
        a_raw = ws.cell(r, 1).value
        section = _section_from_a(a_raw)
        if section:
            current_program = section
            continue

        b = _norm(ws.cell(r, 2).value)
        c = _norm(ws.cell(r, 3).value)
        if b.lower() in SKIP_ROAD or b.lower().startswith("totals"):
            continue
        if not b:
            continue
        if b.lower() == "none":
            skipped.append({"row": r, "road_name": b, "reason": "placeholder"})
            continue

        status = _norm(ws.cell(r, 7).value)
        workflow, unmatched = _status_workflow(status)
        if unmatched:
            unmatched_statuses.append(_norm(unmatched))

        site_number = c or re.sub(r"[^A-Za-z0-9]+", "-", b)[:48].strip("-") or f"ROW-{r}"

        comments = _norm(ws.cell(r, 16).value) or None
        moa_number = _norm(ws.cell(r, 18).value) or None
        councils_raw = _norm(ws.cell(r, 24).value)
        council_names = [x.strip() for x in re.split(r"[,;/]", councils_raw) if x.strip()]
        council_sub = _as_date(ws.cell(r, 25).value)
        council_obj = _as_date(ws.cell(r, 26).value)
        councils = [
            {
                "council_name": name,
                "submitted_to_council_date": council_sub,
                "no_objection_date": council_obj,
            }
            for name in council_names
        ]
        ext = _norm(ws.cell(r, 28).value) or "No"
        if ext.lower() not in ("yes", "no", "n/a", "na"):
            ext = "No"
        if ext.lower() == "na":
            ext = "N/A"
        job_done = _norm(ws.cell(r, 35).value).lower()
        include = a_raw
        include_in_totals = True
        try:
            include_in_totals = int(include or 1) != 0
        except (TypeError, ValueError):
            include_in_totals = True

        start = _as_date(ws.cell(r, 4).value)
        must_have = _as_date(ws.cell(r, 5).value)
        rows_out.append(
            {
                "road_name": b,
                "site_number": site_number,
                "program": current_program,
                "indicative_site_start_date": start,
                "moa_must_have_received_date": must_have,
                "must_have_manual": must_have is not None,
                "comments": comments,
                "moa_number": moa_number,
                "moa_submission_date": _as_date(ws.cell(r, 19).value),
                "moa_received_date": _as_date(ws.cell(r, 20).value),
                "moa_start_date": _as_date(ws.cell(r, 22).value),
                "moa_expiry_date": _as_date(ws.cell(r, 23).value),
                "councils": councils,
                "extension_flag": ext.title() if ext.lower() != "n/a" else "N/A",
                "extension_submission_date": _as_date(ws.cell(r, 29).value),
                "extension_received_date": _as_date(ws.cell(r, 30).value),
                "extension_start_date": _as_date(ws.cell(r, 32).value),
                "extension_expiry_date": _as_date(ws.cell(r, 33).value),
                "job_completed_date": _as_date(ws.cell(r, 34).value),
                "include_in_totals": include_in_totals,
                "workflow": workflow,
                "status_text": status,
                "status_unmatched": unmatched,
                "archive": job_done in ("yes", "y", "true", "1"),
            }
        )
    sheet_name = ws.title
    wb.close()
    unique_unmatched = sorted({s for s in unmatched_statuses if s})
    return {
        "rows": rows_out,
        "skipped": skipped[:80],
        "unmatched_statuses": unique_unmatched,
        "sheet_name": sheet_name,
        "parsed": len(rows_out),
    }


def import_tracker_rows(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    update_existing: bool = True,
) -> dict[str, Any]:
    programs = active_programs(db)
    created = updated = skipped = archived = 0
    errors: list[str] = []

    for raw in rows:
        try:
            road = raw["road_name"]
            site_no = raw["site_number"]
            existing = (
                db.query(Site)
                .filter(Site.road_name.ilike(road), Site.site_number.ilike(site_no))
                .first()
            )
            program = raw.get("program")
            if program and program not in programs:
                pass

            if existing and not update_existing:
                skipped += 1
                continue

            site = existing or Site(road_name=road, site_number=site_no)
            if not existing:
                db.add(site)
                created += 1
            else:
                updated += 1

            site.program = program or site.program
            site.indicative_site_start_date = raw.get("indicative_site_start_date")
            site.moa_must_have_received_date = raw.get("moa_must_have_received_date")
            site.must_have_manual = bool(raw.get("must_have_manual"))
            site.comments = raw.get("comments")
            site.moa_number = raw.get("moa_number")
            site.moa_submission_date = raw.get("moa_submission_date")
            site.moa_received_date = raw.get("moa_received_date")
            site.moa_start_date = raw.get("moa_start_date")
            site.moa_expiry_date = raw.get("moa_expiry_date")
            site.extension_flag = raw.get("extension_flag")
            site.extension_submission_date = raw.get("extension_submission_date")
            site.extension_received_date = raw.get("extension_received_date")
            site.extension_start_date = raw.get("extension_start_date")
            site.extension_expiry_date = raw.get("extension_expiry_date")
            site.job_completed_date = raw.get("job_completed_date")
            site.include_in_totals = bool(raw.get("include_in_totals", True))

            db.flush()
            ensure_workflow_steps(site, db)
            apply_workflow(site, raw.get("workflow"), db)
            set_councils(site, raw.get("councils") or [])
            if raw.get("archive"):
                from datetime import datetime, timezone

                from .services import infer_financial_year

                site.archived = True
                site.archived_at = datetime.now(timezone.utc)
                site.archived_fy = infer_financial_year(site)
                archived += 1
            sync_computed_fields(site, db)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{raw.get('road_name')} / {raw.get('site_number')}: {exc}")

    db.commit()
    return {
        "parsed": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "archived": archived,
        "errors": errors[:50],
    }
