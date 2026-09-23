"""Lifecycle pavements shift report PDF, laid out like the printed WRU form."""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as pdfcanvas

from .lot_map import render_lot_map
from .lot_numbers import build_lot_number, road_number_from_name
from .pdf_brand import VENTIA_LOGO

NAVY = colors.HexColor("#0A3254")
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5c6670")
LINE = colors.HexColor("#d5dbe0")
DIAGRAM_BG = colors.HexColor("#f4f7f8")
POLY = colors.Color(0.05, 0.60, 0.27, alpha=0.35)
POLY_EDGE = colors.HexColor("#0A3254")
PAGE_W, PAGE_H = A4
LEFT = 40
RIGHT = PAGE_W - 40
WIDTH = RIGHT - LEFT


def report_reference(report: dict, site: dict | None = None) -> str:
    details = report.get("details") or {}
    explicit = str(details.get("lot_number") or details.get("report_number") or "").strip()
    road_name = str((site or {}).get("road_name") or report.get("road_name") or "")
    built = build_lot_number(
        work_date=report.get("work_date"),
        road_number=details.get("road_number") or road_number_from_name(road_name),
        fmrp_year=details.get("fmrp_year"),
        site_number=(site or {}).get("site_number") or report.get("site_number"),
        work_kind=details.get("work_kind"),
        mix=details.get("asphalt_type"),
        supervisor=details.get("supervisor") or report.get("crew"),
    )
    # A stored lot that already contains the date is the register number.
    if explicit and explicit[:8].isdigit():
        return explicit
    return built or explicit


def pdf_filename(report: dict, site: dict | None = None) -> str:
    ref = report_reference(report, site) or f"shift-{report.get('id') or 'report'}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-") or "shift-report"
    return f"{safe}.pdf"


def _blank(value) -> bool:
    return value is None or value == ""


def _text(value, empty: str = "") -> str:
    if _blank(value):
        return empty
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value) -> str:
    return _text(value, "0")


def _flag(value) -> str:
    return "TRUE" if value else "FALSE"


def _clock(value) -> str:
    raw = _text(value)
    if not raw:
        return ""
    cleaned = raw.replace("Z", "")
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(cleaned[:19], fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return raw.replace("T", " ")
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return f"{parsed.strftime('%Y-%m-%d')} {hour}:{parsed.strftime('%M')} {parsed.strftime('%p')}"


def _weather_condition(report: dict) -> str:
    details = report.get("details") or {}
    typed = _text(details.get("weather_condition"))
    if typed:
        return typed
    weather = report.get("weather") or {}
    bits = []
    if weather.get("temperature_c") is not None:
        bits.append(f"{round(float(weather['temperature_c']))}c")
    label = weather.get("label") or weather.get("condition")
    if label:
        bits.append(str(label))
    return " ".join(bits)


def _site_name(report: dict, site: dict | None) -> str:
    details = report.get("details") or {}
    road = str((site or {}).get("road_name") or report.get("road_name") or "").strip()
    number = str((site or {}).get("site_number") or report.get("site_number") or "").strip()
    road_no = str(details.get("road_number") or road_number_from_name(road)).strip()
    name = road
    if road_no and road_no not in road:
        name = f"{road} - {road_no}" if road else road_no
    if number and number not in name:
        name = f"{name} Site:{number}" if name else f"Site:{number}"
    return name


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font, size) <= width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def _footer(c: pdfcanvas.Canvas, page: int, ref: str) -> None:
    c.setStrokeColor(LINE)
    c.setLineWidth(0.4)
    c.line(LEFT, 34, RIGHT, 34)
    c.setFillColor(NAVY)
    c.setFont("Helvetica", 8)
    c.drawCentredString(PAGE_W / 2, 42, f"Page {page} of 3")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(LEFT, 22, ref[:42])
    c.drawCentredString(PAGE_W / 2, 22, "Uncontrolled when printed or downloaded")
    c.drawRightString(RIGHT, 22, "Revision 0")
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(LEFT, 12, "Internal")


def _header(c: pdfcanvas.Canvas, ref: str) -> float:
    if VENTIA_LOGO.is_file():
        try:
            c.drawImage(
                ImageReader(str(VENTIA_LOGO)),
                RIGHT - 78,
                PAGE_H - 58,
                width=78,
                height=40,
                preserveAspectRatio=True,
                mask="auto",
                anchor="c",
            )
        except Exception:
            pass
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, PAGE_H - 36, "WRU Lifecycle Pavements Shift Report")
    if ref:
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(LEFT, PAGE_H - 50, ref)
    return PAGE_H - 64


def _section(c: pdfcanvas.Canvas, y: float, title: str) -> float:
    c.setFillColor(NAVY)
    c.rect(LEFT, y - 16, WIDTH, 16, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT + 6, y - 11.5, title)
    return y - 16


def _pair(c: pdfcanvas.Canvas, y: float, left: tuple[str, str], right: tuple[str, str] | None) -> float:
    col_w = WIDTH / 2
    label_w = 108
    value_w = col_w - label_w - 12
    blocks = [left, right or ("", "")]
    heights = []
    wrapped = []
    for label, value in blocks:
        lines = _wrap(value or "", "Helvetica", 8, value_w if label else col_w - 8)
        wrapped.append(lines)
        heights.append(max(16, 10 + 10 * max(1, len(lines))))
    height = max(heights)
    for index, (label, _value) in enumerate(blocks):
        if not label and not (right and index == 1):
            continue
        x = LEFT + index * col_w
        c.setStrokeColor(LINE)
        c.setLineWidth(0.3)
        c.line(x, y - height, x + col_w, y - height)
        if label:
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(x + 4, y - 12, label)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8)
        lines = wrapped[index]
        text_x = x + 4 + (label_w if label else 0)
        for line_no, line in enumerate(lines[:6]):
            c.drawString(text_x, y - 12 - line_no * 10, line)
    return y - height


def _note_block(c: pdfcanvas.Canvas, y: float, title: str, body: str, height: float) -> float:
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(LEFT + 2, y - 11, title)
    top = y - 16
    c.setStrokeColor(LINE)
    c.setFillColor(colors.white)
    c.setLineWidth(0.6)
    c.rect(LEFT, top - height, WIDTH, height, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica", 8)
    lines = _wrap(body or "NULL", "Helvetica", 8, WIDTH - 16)
    cursor = top - 14
    for line in lines:
        if cursor < top - height + 6:
            break
        c.drawString(LEFT + 8, cursor, line)
        cursor -= 11
    return top - height - 8


def _rings(polygons: list) -> list[list[tuple[float, float]]]:
    rings: list[list[tuple[float, float]]] = []
    for feature in polygons or []:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry") if feature.get("type") == "Feature" else feature
        if not isinstance(geom, dict):
            continue
        kind = geom.get("type")
        coords = geom.get("coordinates") or []
        if kind == "Polygon" and coords:
            rings.append([(float(pt[0]), float(pt[1])) for pt in coords[0]])
        elif kind == "MultiPolygon":
            for poly in coords:
                if poly:
                    rings.append([(float(pt[0]), float(pt[1])) for pt in poly[0]])
    return [ring for ring in rings if len(ring) >= 3]


def _diagram(c: pdfcanvas.Canvas, y: float, polygons: list, lot_number: str) -> float:
    height = 168
    c.setStrokeColor(LINE)
    c.setFillColor(DIAGRAM_BG)
    c.setLineWidth(0.6)
    c.rect(LEFT, y - height, WIDTH, height, fill=1, stroke=1)
    image = None
    try:
        image = render_lot_map(polygons, lot_number, width=1100, height=420)
    except Exception:
        image = None
    if image:
        from io import BytesIO

        from reportlab.lib.utils import ImageReader

        c.drawImage(
            ImageReader(BytesIO(image)),
            LEFT,
            y - height,
            width=WIDTH,
            height=height,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        return y - height
    rings = _rings(polygons)
    if not rings:
        c.setFillColor(MUTED)
        c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(PAGE_W / 2, y - height / 2 + 8, "Lot diagram")
        if lot_number:
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(RIGHT - 8, y - height + 8, lot_number)
        return y - height
    points = [pt for ring in rings for pt in ring]
    min_x = min(pt[0] for pt in points)
    max_x = max(pt[0] for pt in points)
    min_y = min(pt[1] for pt in points)
    max_y = max(pt[1] for pt in points)
    span_x = max(max_x - min_x, 0.00001)
    span_y = max(max_y - min_y, 0.00001)
    pad = 14
    box_w = WIDTH - pad * 2
    box_h = height - pad * 2
    scale = min(box_w / span_x, box_h / span_y)
    drawn_w = span_x * scale
    drawn_h = span_y * scale
    origin_x = LEFT + pad + (box_w - drawn_w) / 2
    origin_y = (y - height) + pad + (box_h - drawn_h) / 2
    for ring in rings:
        path = c.beginPath()
        for index, (lng, lat) in enumerate(ring):
            px = origin_x + (lng - min_x) * scale
            py = origin_y + (lat - min_y) * scale
            if index == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.close()
        c.setFillColor(POLY)
        c.setStrokeColor(POLY_EDGE)
        c.setLineWidth(1.2)
        c.drawPath(path, fill=1, stroke=1)
    if lot_number:
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(RIGHT - 8, y - height + 8, lot_number)
    return y - height


def build_shift_report_pdf(report: dict, site: dict | None = None) -> bytes:
    details = report.get("details") or {}
    ref = report_reference(report, site)
    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    c.setTitle(ref or "WRU Lifecycle Pavements Shift Report")

    y = _header(c, ref)
    y = _section(c, y, "General Information")
    y = _pair(c, y, ("Date", _text(report.get("work_date"))), ("Ventia Supervisor", _text(details.get("supervisor"))))
    y = _pair(c, y, ("FMRP Year", _text(details.get("fmrp_year"))), ("Weather Condition", _weather_condition(report)))
    y = _pair(c, y, ("Site Name", _site_name(report, site)), ("Shift Type", _text(report.get("shift_type")).title()))
    y = _pair(c, y, ("Lot Number", ref), ("High Risk Activity", _text(details.get("high_risk"))))
    y -= 6
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(LEFT + 2, y - 11, "Lot Diagram")
    y = _diagram(c, y - 16, report.get("polygons") or [], ref)

    y -= 8
    y = _section(c, y, "Subcontractor Information")
    y = _pair(
        c,
        y,
        ("Paving Contractor", _text(details.get("paving_contractor"))),
        ("Traffic Contractor", _text(details.get("traffic_contractor"))),
    )
    y = _pair(c, y, ("Other Contractor", _text(details.get("other_contractors"))), ("", ""))

    y -= 6
    y = _section(c, y, "Traffic Information")
    y = _pair(c, y, ("Road Opened", _clock(details.get("road_opened"))), ("Road Closed", _clock(details.get("road_closed"))))
    y = _pair(
        c,
        y,
        ("Traffic Crew Start", _clock(details.get("traffic_crew_start"))),
        ("Traffic Crew End", _clock(details.get("traffic_crew_end"))),
    )
    y = _pair(c, y, ("TGS Number", _text(details.get("tgs_number"))), ("MOA Number", _text(details.get("moa_number"))))
    y = _pair(c, y, ("MOA Start Time", _clock(details.get("moa_start"))), ("MOA End Time", _clock(details.get("moa_end"))))
    y = _pair(
        c,
        y,
        ("Total TC", _number(details.get("total_tc"))),
        ("No of Arrow Boards", _number(details.get("arrow_boards"))),
    )

    y -= 6
    y = _section(c, y, "Paving Information")
    y = _pair(
        c,
        y,
        ("Asphalt Type", _text(details.get("asphalt_type"))),
        ("Other Material Used", _number(details.get("other_material"))),
    )
    y = _pair(c, y, ("Area", _number(details.get("shift_area_m2"))), ("Tonnage", _number(details.get("tonnage"))))
    y = _pair(c, y, ("Chainage", _text(details.get("chainage"))), ("Description", _text(details.get("description"))))
    y = _pair(
        c,
        y,
        ("#Pits To Be Raised", _number(details.get("pits"))),
        ("#Valves To Be Raised", _number(details.get("valves"))),
    )
    y = _pair(c, y, ("#Loops Present", _number(details.get("loops"))), ("", ""))
    _footer(c, 1, ref)
    c.showPage()

    y = _header(c, ref)
    y = _section(c, y, "Site Observations")
    y -= 4
    block_h = 118
    y = _note_block(c, y, "Prestart Notes", _text(details.get("prestart_notes"), "NULL"), block_h)
    y = _note_block(c, y, "Profiling Notes", _text(details.get("profiling_notes"), "NULL"), block_h)
    y = _note_block(c, y, "Asphalting Notes", _text(details.get("asphalting_notes"), "NULL"), block_h)
    _note_block(c, y, "General Observations", _text(details.get("observations"), "NULL"), block_h)
    _footer(c, 2, ref)
    c.showPage()

    y = _header(c, ref)
    y = _section(c, y, "TMP Checks")
    y = _pair(c, y, ("Prestart Done", _flag(details.get("prestart_done"))), ("Plant Prestart Done", _flag(details.get("plant_prestart_done"))))
    y = _pair(c, y, ("TM Implementation", _flag(details.get("tm_implementation"))), ("After Care Check", _flag(details.get("aftercare"))))
    y -= 8
    y = _note_block(c, y, "Incident Issues", _text(details.get("incidents"), "NULL"), 70)
    y = _note_block(c, y, "Comments", _text(details.get("comments"), "NULL"), 70)
    y -= 4
    y = _section(c, y, "Non Conformance Reports")
    y = _pair(
        c,
        y,
        ("NCR Raised", _flag(details.get("ncr_raised"))),
        ("VenSafe Event No.", _text(details.get("vensafe_event"), "N/A")),
    )
    y = _note_block(c, y, "Non-Compliance Details", _text(details.get("non_compliance"), "NULL"), 70)
    y -= 4
    y = _section(c, y, "Photos")
    _note_block(c, y, "SharePoint URL", _text(details.get("photos_url"), "NULL"), 64)
    _footer(c, 3, ref)
    c.save()
    return buf.getvalue()
