"""Mobile-friendly shift report PDF."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .pdf_brand import GREEN_HEX, branded_margins


def _weather_line(weather: dict | None) -> str:
    w = weather or {}
    bits = [w.get("label") or "—"]
    if w.get("temperature_c") is not None:
        bits.append(f"{w['temperature_c']}°C")
    if w.get("wind_kmh") is not None:
        bits.append(f"wind {w['wind_kmh']} km/h")
    if w.get("rain_mm"):
        bits.append(f"rain {w['rain_mm']} mm")
    return " · ".join(str(b) for b in bits if b)


def build_shift_report_pdf(report: dict, site: dict | None = None) -> bytes:
    buf = BytesIO()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("H", parent=styles["Heading1"], textColor=colors.HexColor(f"#{GREEN_HEX}"), fontSize=16)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=10, leading=14)
    doc = SimpleDocTemplate(buf, pagesize=A4, **branded_margins(landscape_mode=False))
    story = [
        Paragraph("WRU shift report", title),
        Spacer(1, 6),
        Paragraph(
            f"{(site or {}).get('road_name') or ''} {(site or {}).get('site_number') or ''}".strip() or "Site",
            body,
        ),
        Paragraph(
            f"{report.get('work_date') or ''} · {(report.get('shift_type') or 'day').title()} shift"
            + (f" · {report.get('crew')}" if report.get("crew") else ""),
            body,
        ),
        Spacer(1, 8),
        Paragraph(f"<b>Weather</b> — {_weather_line(report.get('weather'))}", body),
    ]
    log = report.get("weather_log") or []
    if log:
        story.append(Paragraph("<b>Weather changes</b>", body))
        for item in log:
            story.append(
                Paragraph(
                    f"{item.get('observed_at') or ''}: {_weather_line(item)}",
                    body,
                )
            )
    for label, key in (("Works done", "works_done"), ("Issues", "issues"), ("Notes", "notes")):
        value = (report.get(key) or "").strip()
        if value:
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>{label}</b>", body))
            story.append(Paragraph(value.replace("\n", "<br/>"), body))
    details = report.get("details") or {}
    labels = [
        ("FMRP year", "fmrp_year"),
        ("Lot", "lot_number"),
        ("Supervisor", "supervisor"),
        ("High risk", "high_risk"),
        ("Chainage", "chainage"),
        ("Road closed", "road_closed"),
        ("Road opened", "road_opened"),
        ("Traffic contractor", "traffic_contractor"),
        ("TGS", "tgs_number"),
        ("MoA", "moa_number"),
        ("MoA start", "moa_start"),
        ("MoA end", "moa_end"),
        ("Traffic crew start", "traffic_crew_start"),
        ("Traffic crew end", "traffic_crew_end"),
        ("Total TC", "total_tc"),
        ("Vehicles", "vehicles"),
        ("Arrow boards", "arrow_boards"),
        ("Paving contractor", "paving_contractor"),
        ("Asphalt type", "asphalt_type"),
        ("Thickness mm", "thickness_mm"),
        ("Area this shift m²", "shift_area_m2"),
        ("Site total m²", "site_area_m2"),
        ("Tonnage", "tonnage"),
        ("Prestart notes", "prestart_notes"),
        ("Profiling notes", "profiling_notes"),
        ("Asphalting notes", "asphalting_notes"),
        ("Observations", "observations"),
        ("Incidents", "incidents"),
        ("Comments", "comments"),
    ]
    for label, key in labels:
        value = details.get(key)
        if value in (None, "", False):
            continue
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>{label}</b> — {str(value).replace(chr(10), '<br/>')}", body))
    polygons = report.get("polygons") or []
    if polygons:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"<b>Work polygons</b> — {len(polygons)}", body))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Logged by {report.get('created_by') or '—'}", body))
    doc.build(story)
    return buf.getvalue()
