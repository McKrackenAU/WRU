from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..calculations import on_permits_priority_list
from ..database import get_db
from ..models import WORKFLOW_LABELS, Site
from ..services import site_to_dict

router = APIRouter(prefix="/api/export", tags=["export"])


def _priority_rows(db: Session) -> list[dict]:
    sites = db.query(Site).filter(Site.archived.is_(False)).all()
    rows = []
    for site in sites:
        if not on_permits_priority_list(site):
            continue
        data = site_to_dict(site)
        metrics = data["metrics"]
        current = metrics.get("current_stage")
        rows.append(
            {
                "priority": data["today_priority"],
                "rank": metrics.get("permits_priority_rank"),
                "road_name": site.road_name,
                "site_number": site.site_number,
                "program": site.program or "",
                "councils": "; ".join(data["councils"]),
                "indicative_start": site.indicative_site_start_date.isoformat()
                if site.indicative_site_start_date
                else "",
                "days_to_start": metrics.get("days_to_start")
                if metrics.get("days_to_start") is not None
                else "",
                "moa_must_have": site.moa_must_have_received_date.isoformat()
                if site.moa_must_have_received_date
                else "",
                "must_have_status": metrics.get("must_have_status", {}).get("label", ""),
                "moa_number": site.moa_number or "",
                "moa_submission_date": site.moa_submission_date.isoformat()
                if site.moa_submission_date
                else "",
                "tgs_reference": site.tgs_reference or "",
                "current_stage": WORKFLOW_LABELS.get(current or "", current or ""),
                "progress_pct": metrics.get("workflow_progress_pct", 0),
                "comments": (site.comments or "").replace("\n", " "),
            }
        )
    rows.sort(key=lambda r: (r["priority"], r["rank"] if r["rank"] is not None else 999999))
    return rows


@router.get("/priority-list.csv")
def export_priority_csv(db: Session = Depends(get_db)):
    rows = _priority_rows(db)
    buf = io.StringIO()
    fieldnames = [
        "priority",
        "road_name",
        "site_number",
        "program",
        "councils",
        "indicative_start",
        "days_to_start",
        "moa_must_have",
        "must_have_status",
        "moa_number",
        "moa_submission_date",
        "tgs_reference",
        "current_stage",
        "progress_pct",
        "comments",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    filename = f"WRU_TGS_priority_list_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sites.csv")
def export_sites_csv(archived: bool = False, db: Session = Depends(get_db)):
    sites = db.query(Site).filter(Site.archived.is_(archived)).all()
    buf = io.StringIO()
    fieldnames = [
        "id",
        "road_name",
        "site_number",
        "program",
        "councils",
        "financial_year",
        "priority",
        "indicative_start",
        "moa_must_have",
        "moa_number",
        "current_stage",
        "progress_pct",
        "on_permits_priority_list",
        "archived",
        "comments",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for site in sites:
        data = site_to_dict(site)
        m = data["metrics"]
        writer.writerow(
            {
                "id": site.id,
                "road_name": site.road_name,
                "site_number": site.site_number,
                "program": site.program or "",
                "councils": "; ".join(data["councils"]),
                "financial_year": data["financial_year"],
                "priority": data["today_priority"],
                "indicative_start": site.indicative_site_start_date or "",
                "moa_must_have": site.moa_must_have_received_date or "",
                "moa_number": site.moa_number or "",
                "current_stage": WORKFLOW_LABELS.get(m.get("current_stage") or "", m.get("current_stage") or ""),
                "progress_pct": m.get("workflow_progress_pct", 0),
                "on_permits_priority_list": m.get("on_permits_priority_list"),
                "archived": site.archived,
                "comments": (site.comments or "").replace("\n", " "),
            }
        )
    kind = "archive" if archived else "active"
    filename = f"WRU_TGS_{kind}_sites_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
