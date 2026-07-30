from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy.orm import Session

from ..calculations import COUNCIL_NO_OBJECTION_BUSINESS_DAYS
from ..database import get_db
from ..models import Site
from ..services import site_to_dict
from ..stage_registry import stage_labels_map

router = APIRouter(prefix="/api/export", tags=["export"])


def _client_list_rows(db: Session, *, team: str) -> list[dict]:
    """team: permits | trims"""
    labels = stage_labels_map(db)
    sites = db.query(Site).filter(Site.archived.is_(False)).all()
    rows = []
    for site in sites:
        data = site_to_dict(site, db=db)
        metrics = data["metrics"]
        flag = (
            metrics.get("on_permits_priority_list")
            if team == "permits"
            else metrics.get("on_trims_priority_list")
        )
        if not flag:
            continue
        current = metrics.get("current_stage")
        council_bits = []
        for c in metrics.get("councils") or []:
            wait = c.get("business_days_waiting")
            council_bits.append(
                f"{c['council_name']}: {c.get('status_label')}"
                + (f" [{wait} bus. days]" if wait is not None and c.get("status") == "waiting" else "")
            )
        rows.append(
            {
                "team": team,
                "priority": data["today_priority"],
                "rank": metrics.get("permits_priority_rank"),
                "road_name": site.road_name,
                "site_number": site.site_number,
                "program": site.program or "",
                "councils": "; ".join(data["councils"]),
                "council_status": " | ".join(council_bits),
                "business_days_waiting": metrics.get("max_council_business_days_waiting")
                if metrics.get("max_council_business_days_waiting") is not None
                else "",
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
                "current_stage": labels.get(current or "", current or ""),
                "progress_pct": metrics.get("workflow_progress_pct", 0),
                "client_list": metrics.get("client_list"),
                "is_generic_moa": "yes" if data.get("is_generic_moa") else "",
                "comments": (site.comments or "").replace("\n", " "),
            }
        )
    rows.sort(key=lambda r: (r["priority"], r["rank"] if r["rank"] is not None else 999999))
    return rows


CLIENT_FIELDS = [
    "priority",
    "road_name",
    "site_number",
    "program",
    "councils",
    "council_status",
    "business_days_waiting",
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


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CLIENT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _xlsx_bytes(rows: list[dict], sheet_name: str, title: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.cell(1, 1, title).font = Font(bold=True, size=13)
    ws.cell(
        2,
        1,
        f"Exported {date.today().isoformat()} · Council no-objection assumed after "
        f"{COUNCIL_NO_OBJECTION_BUSINESS_DAYS} business days without response",
    )
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0B3D2E")
    for col, h in enumerate(CLIENT_FIELDS, 1):
        cell = ws.cell(4, col, h)
        cell.font = header_font
        cell.fill = header_fill
    for r_idx, row in enumerate(rows, start=5):
        for c_idx, key in enumerate(CLIENT_FIELDS, 1):
            ws.cell(r_idx, c_idx, row.get(key, ""))
    for col in ws.columns:
        letter = col[0].column_letter
        width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
        ws.column_dimensions[letter].width = min(max(width + 2, 12), 48)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/priority-list.csv")
def export_permits_priority_csv(db: Session = Depends(get_db)):
    """Legacy alias — Permits team client list."""
    rows = _client_list_rows(db, team="permits")
    return _csv_response(rows, f"WRU_Permits_priority_{date.today().isoformat()}.csv")


@router.get("/permits-list.csv")
def export_permits_csv(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="permits")
    return _csv_response(rows, f"WRU_Permits_list_{date.today().isoformat()}.csv")


@router.get("/trims-list.csv")
def export_trims_csv(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="trims")
    return _csv_response(rows, f"WRU_TRIMS_list_{date.today().isoformat()}.csv")


@router.get("/permits-list.xlsx")
def export_permits_xlsx(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="permits")
    data = _xlsx_bytes(rows, "Permits", "WRU TGS Tracker — Permits team priority list")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="WRU_Permits_list_{date.today().isoformat()}.xlsx"'
        },
    )


@router.get("/trims-list.xlsx")
def export_trims_xlsx(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="trims")
    data = _xlsx_bytes(rows, "TRIMS", "WRU TGS Tracker — TRIMS team priority list")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="WRU_TRIMS_list_{date.today().isoformat()}.xlsx"'
        },
    )


@router.get("/sites.csv")
def export_sites_csv(archived: bool = False, db: Session = Depends(get_db)):
    labels = stage_labels_map(db)
    sites = db.query(Site).filter(Site.archived.is_(archived)).all()
    buf = io.StringIO()
    fieldnames = [
        "id",
        "road_name",
        "site_number",
        "program",
        "councils",
        "council_status",
        "business_days_waiting",
        "financial_year",
        "priority",
        "indicative_start",
        "moa_must_have",
        "moa_number",
        "current_stage",
        "progress_pct",
        "client_list",
        "on_permits_priority_list",
        "on_trims_priority_list",
        "is_generic_moa",
        "archived",
        "comments",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for site in sites:
        data = site_to_dict(site, db=db)
        m = data["metrics"]
        council_bits = [f"{c['council_name']}: {c.get('status_label')}" for c in (m.get("councils") or [])]
        writer.writerow(
            {
                "id": site.id,
                "road_name": site.road_name,
                "site_number": site.site_number,
                "program": site.program or "",
                "councils": "; ".join(data["councils"]),
                "council_status": " | ".join(council_bits),
                "business_days_waiting": m.get("max_council_business_days_waiting")
                if m.get("max_council_business_days_waiting") is not None
                else "",
                "financial_year": data["financial_year"],
                "priority": data["today_priority"],
                "indicative_start": site.indicative_site_start_date or "",
                "moa_must_have": site.moa_must_have_received_date or "",
                "moa_number": site.moa_number or "",
                "current_stage": labels.get(m.get("current_stage") or "", m.get("current_stage") or ""),
                "progress_pct": m.get("workflow_progress_pct", 0),
                "client_list": m.get("client_list"),
                "on_permits_priority_list": m.get("on_permits_priority_list"),
                "on_trims_priority_list": m.get("on_trims_priority_list"),
                "is_generic_moa": data.get("is_generic_moa"),
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
