"""Landscape MS Project–style Gantt PDF export."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .pdf_brand import GREEN, GREEN_MID, MUTED, ROW_ALT, RULE, branded_margins, draw_branded_page


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _fmt(d: date | None) -> str:
    if not d:
        return "—"
    return d.strftime("%d/%m/%Y")


class GanttTimeline(Flowable):
    """Draw left task labels + horizontal bars across a day/week axis."""

    def __init__(
        self,
        items: list[dict[str, Any]],
        *,
        width: float,
        row_h: float = 16,
        label_w: float = 95 * mm,
    ):
        super().__init__()
        self.items = items
        self.width = width
        self.row_h = row_h
        self.label_w = label_w
        self.header_h = 22
        self._span = self._compute_span()

    def _compute_span(self) -> tuple[date, date]:
        starts = [_parse_iso(i.get("planned_start")) for i in self.items]
        ends = [_parse_iso(i.get("planned_end")) for i in self.items]
        valid_s = [d for d in starts if d]
        valid_e = [d for d in ends if d]
        if not valid_s or not valid_e:
            today = date.today()
            return today, today + timedelta(days=14)
        start = min(valid_s)
        end = max(valid_e)
        if end < start:
            end = start
        # pad a day each side
        return start - timedelta(days=1), end + timedelta(days=1)

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        h = self.header_h + max(1, len(self.items)) * self.row_h + 4
        return self.width, h

    def draw(self):
        c = self.canv
        span_start, span_end = self._span
        days = max(1, (span_end - span_start).days + 1)
        chart_w = max(40, self.width - self.label_w)
        day_w = chart_w / days
        use_weeks = days > 45

        # Header band
        c.setFillColor(GREEN)
        c.rect(0, self.height - self.header_h, self.width, self.header_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(3, self.height - 14, "#  Road / Site")
        c.drawRightString(self.label_w - 4, self.height - 14, "Dates")

        # Axis ticks
        c.setFont("Helvetica", 6)
        if use_weeks:
            cursor = span_start
            while cursor <= span_end:
                x = self.label_w + (cursor - span_start).days * day_w
                c.setFillColor(colors.white)
                c.drawString(x + 1, self.height - 14, cursor.strftime("%d/%m"))
                cursor += timedelta(days=7)
        else:
            step = 1 if days <= 21 else (2 if days <= 40 else 3)
            for i in range(0, days, step):
                d = span_start + timedelta(days=i)
                x = self.label_w + i * day_w
                c.setFillColor(colors.white)
                c.drawString(x + 1, self.height - 14, d.strftime("%d/%m"))

        # Rows
        for idx, item in enumerate(self.items):
            y = self.height - self.header_h - (idx + 1) * self.row_h
            if idx % 2:
                c.setFillColor(ROW_ALT)
                c.rect(0, y, self.width, self.row_h, fill=1, stroke=0)

            road = (item.get("site_road_name") or "Site")[:34]
            site_no = item.get("site_number") or ""
            label = f"{idx + 1}. {road}"
            c.setFillColor(colors.HexColor("#1a1a1a"))
            c.setFont("Helvetica", 7)
            c.drawString(3, y + 5, label)
            if site_no:
                c.setFillColor(MUTED)
                c.setFont("Helvetica", 6)
                c.drawString(3, y + 0.5, str(site_no)[:18])

            start = _parse_iso(item.get("planned_start"))
            end = _parse_iso(item.get("planned_end"))
            date_txt = f"{_fmt(start)}–{_fmt(end)}"
            c.setFillColor(MUTED)
            c.setFont("Helvetica", 6)
            c.drawRightString(self.label_w - 3, y + 4, date_txt)

            # Vertical separator
            c.setStrokeColor(RULE)
            c.setLineWidth(0.4)
            c.line(self.label_w, y, self.label_w, y + self.row_h)

            if start and end:
                s_off = max(0, (start - span_start).days)
                e_off = min(days - 1, (end - span_start).days)
                if e_off >= s_off:
                    bx = self.label_w + s_off * day_w
                    bw = max(day_w * 0.8, (e_off - s_off + 1) * day_w - 1)
                    c.setFillColor(GREEN_MID)
                    c.roundRect(bx, y + 3.5, bw, self.row_h - 7, 2, fill=1, stroke=0)

        # Outer border
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.rect(0, 0, self.width, self.height, fill=0, stroke=1)


def build_gantt_pdf(
    board: dict[str, Any],
    *,
    filter_label: str | None = None,
) -> bytes:
    items = list(board.get("items") or [])
    program = board.get("program") or "Program"
    title = f"Works Gantt — {program}"
    subtitle_bits = [f"{len(items)} site(s)"]
    if filter_label:
        subtitle_bits.insert(0, filter_label)

    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        title=title,
        **branded_margins(landscape_mode=True),
    )
    doc.brand_eyebrow = "WORKS GANTT"
    doc.brand_title = title
    doc.brand_subtitle = " · ".join(subtitle_bits)
    doc.brand_doc_kind = "Gantt"
    doc.brand_product = "WRU TGS TRACKER"
    doc.brand_footer_meta = f"{program} · {len(items)} site(s)"

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Th",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Td",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor("#1a1a1a"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="FootNote",
            parent=styles["Normal"],
            fontSize=7.5,
            leading=9,
            textColor=MUTED,
            spaceBefore=6,
        )
    )

    usable_w = page[0] - doc.leftMargin - doc.rightMargin
    headers = ["#", "Road", "Site", "Shifts", "Asphalt", "Traffic", "Start", "End"]
    data: list[list[Any]] = [[Paragraph(h, styles["Th"]) for h in headers]]
    if not items:
        data.append([Paragraph("No sites on this Gantt export.", styles["Td"])] + [""] * 7)
    else:
        for idx, item in enumerate(items, start=1):
            data.append(
                [
                    Paragraph(str(idx), styles["Td"]),
                    Paragraph(str(item.get("site_road_name") or "—")[:48], styles["Td"]),
                    Paragraph(str(item.get("site_number") or "—"), styles["Td"]),
                    Paragraph(str(item.get("shifts_count") or 1), styles["Td"]),
                    Paragraph(str(item.get("subcontractor_name") or "—")[:28], styles["Td"]),
                    Paragraph(str(item.get("traffic_contractor_name") or "—")[:28], styles["Td"]),
                    Paragraph(_fmt(_parse_iso(item.get("planned_start"))), styles["Td"]),
                    Paragraph(_fmt(_parse_iso(item.get("planned_end"))), styles["Td"]),
                ]
            )

    col_w = [10 * mm, 52 * mm, 20 * mm, 14 * mm, 40 * mm, 40 * mm, 22 * mm, 22 * mm]
    table = Table(data, colWidths=col_w, repeatRows=1)
    style_cmds: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
    ]
    if not items:
        style_cmds.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(style_cmds))

    story: list[Any] = [
        table,
        Spacer(1, 5 * mm),
        GanttTimeline(items, width=usable_w),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Exported {datetime.now().strftime('%d/%m/%Y %H:%M')} · Ventia confidential works sequence.",
            styles["FootNote"],
        ),
    ]
    doc.build(story, onFirstPage=draw_branded_page, onLaterPages=draw_branded_page)
    return buf.getvalue()
