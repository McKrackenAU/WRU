from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
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


def _pdf_cell(text: Any, style: ParagraphStyle) -> Paragraph:
    raw = "" if text is None else str(text)
    safe = (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe or "—", style)


def _pdf_bytes(rows: list[dict], *, title: str, team_label: str) -> bytes:
    """Landscape A4 priority list suitable for client meetings / print."""
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ListTitle",
            parent=styles["Heading1"],
            textColor=colors.HexColor("#0B3D2E"),
            fontSize=14,
            leading=17,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ListSub",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#445055"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Th",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Td",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TdCenter",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9,
            alignment=TA_CENTER,
        )
    )

    story: list[Any] = [
        Paragraph(title, styles["ListTitle"]),
        Paragraph(
            f"{team_label} · Exported {date.today().isoformat()} · {len(rows)} site(s) · "
            f"Council no-objection assumed after {COUNCIL_NO_OBJECTION_BUSINESS_DAYS} business days",
            styles["ListSub"],
        ),
    ]

    headers = [
        "Pri",
        "Road",
        "Site",
        "Program",
        "Stage",
        "Start",
        "Must-have",
        "Council / wait",
        "MoA #",
        "Comments",
    ]
    data: list[list[Any]] = [[_pdf_cell(h, styles["Th"]) for h in headers]]

    if not rows:
        data.append([_pdf_cell("No sites on this priority list.", styles["Td"])] + [""] * 9)
    else:
        for row in rows:
            wait = row.get("business_days_waiting")
            council = row.get("councils") or ""
            if wait not in ("", None):
                council = f"{council} ({wait}d)" if council else f"{wait}d"
            must = row.get("moa_must_have") or ""
            must_label = row.get("must_have_status") or ""
            if must_label and must_label != "—":
                must = f"{must} · {must_label}" if must else must_label
            comments = (row.get("comments") or "")[:160]
            data.append(
                [
                    _pdf_cell(row.get("priority"), styles["TdCenter"]),
                    _pdf_cell(row.get("road_name"), styles["Td"]),
                    _pdf_cell(row.get("site_number"), styles["Td"]),
                    _pdf_cell(row.get("program"), styles["Td"]),
                    _pdf_cell(row.get("current_stage"), styles["Td"]),
                    _pdf_cell(row.get("indicative_start"), styles["Td"]),
                    _pdf_cell(must, styles["Td"]),
                    _pdf_cell(council, styles["Td"]),
                    _pdf_cell(row.get("moa_number"), styles["Td"]),
                    _pdf_cell(comments, styles["Td"]),
                ]
            )

    # Usable width on landscape A4 with 10mm margins ≈ 277mm
    col_widths = [
        12 * mm,  # Pri
        42 * mm,  # Road
        18 * mm,  # Site
        28 * mm,  # Program
        32 * mm,  # Stage
        20 * mm,  # Start
        28 * mm,  # Must-have
        36 * mm,  # Council
        20 * mm,  # MoA
        41 * mm,  # Comments
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C5D0C8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F4")]),
    ]
    # Highlight priority 1 rows
    for i, row in enumerate(rows, start=1):
        if str(row.get("priority")) == "1":
            style_cmds.append(
                ("BACKGROUND", (0, i), (0, i), colors.HexColor("#FDE8D8"))
            )
    if not rows:
        style_cmds.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "WRU TGS Tracker · Ventia — confidential priority list for client coordination.",
            styles["ListSub"],
        )
    )
    doc.build(story)
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


@router.get("/permits-list.pdf")
def export_permits_pdf(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="permits")
    data = _pdf_bytes(
        rows,
        title="DTP — Permits priority list",
        team_label="Permits team",
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="WRU_Permits_list_{date.today().isoformat()}.pdf"'
        },
    )


@router.get("/trims-list.pdf")
def export_trims_pdf(db: Session = Depends(get_db)):
    rows = _client_list_rows(db, team="trims")
    data = _pdf_bytes(
        rows,
        title="DTP — TRIMS priority list",
        team_label="TRIMS team",
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="WRU_TRIMS_list_{date.today().isoformat()}.pdf"'
        },
    )


@router.get("/priority-list.pdf")
def export_permits_priority_pdf(db: Session = Depends(get_db)):
    """Legacy alias — Permits team PDF."""
    return export_permits_pdf(db)


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
