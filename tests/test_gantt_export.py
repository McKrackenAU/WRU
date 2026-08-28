"""Gantt PDF export pagination, columns, and calendar helpers."""

from datetime import date, timedelta
from pathlib import Path
import base64
import re
import zlib

from reportlab.lib.pagesizes import A4, landscape

from app.gantt_export import GanttTimeline, ROWS_PER_TIMELINE_PAGE, build_gantt_pdf
from app.pdf_brand import branded_margins

ROOT = Path(__file__).resolve().parents[1]
GANTT_HTML = (ROOT / "app/static/gantt.html").read_text(encoding="utf-8")
GANTT_JS = (ROOT / "app/static/js/gantt.js").read_text(encoding="utf-8")


def _item(i: int, start: date, *, shift_type: str = "day"):
    end = start + timedelta(days=2)
    return {
        "site_road_name": f"Road {i}",
        "site_number": f"S{i:03d}",
        "shifts_count": 3,
        "shift_type": shift_type,
        "subcontractor_name": "Asphalt Co",
        "traffic_contractor_name": "Traffic Co",
        "planned_start": start.isoformat(),
        "planned_end": end.isoformat(),
    }


def _pdf_text(data: bytes) -> str:
    """Best-effort text extraction from a ReportLab PDF (ASCII85 + Flate)."""
    parts: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.+?)endstream", data, re.S):
        raw = m.group(1).strip()
        try:
            payload = raw.strip()
            if not payload.startswith(b"<~"):
                payload = b"<~" + payload
            if not payload.rstrip().endswith(b"~>"):
                payload = payload.rstrip() + b"~>"
            chunk = zlib.decompress(base64.a85decode(payload, adobe=True))
        except (ValueError, zlib.error):
            continue
        if b"Tj" not in chunk and b"TJ" not in chunk:
            continue
        for s in re.findall(rb"\((?:\\.|[^\\)])*\)", chunk):
            text = s[1:-1].decode("latin-1", "replace")
            text = text.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
            parts.append(text)
    return " ".join(parts)


def _frame():
    page = landscape(A4)
    m = branded_margins(landscape_mode=True)
    return (
        page[0] - m["leftMargin"] - m["rightMargin"],
        page[1] - m["topMargin"] - m["bottomMargin"],
    )


def test_gantt_pdf_exports_large_board():
    start = date(2026, 3, 2)
    items = [_item(i, start + timedelta(days=i * 3)) for i in range(40)]
    assert len(items) > ROWS_PER_TIMELINE_PAGE
    pdf = build_gantt_pdf({"program": "Lifecycle pavements", "items": items})
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2000


def test_gantt_pdf_table_has_day_night_not_contractors():
    items = [
        {
            "site_road_name": "Test Road",
            "site_number": "S015",
            "shifts_count": 1,
            "shift_type": "night",
            "subcontractor_name": "Asphalt Co",
            "traffic_contractor_name": "Traffic Co",
            "planned_start": "2026-09-13",
            "planned_end": "2026-09-14",
        }
    ]
    pdf = build_gantt_pdf({"program": "LCP-FMRP", "items": items})
    text = _pdf_text(pdf)
    assert "Day / Night" in text
    assert "13/09/2026" in text
    assert "14/09/2026" in text
    assert "Night" in text
    assert "Asphalt" not in text
    assert "Traffic" not in text
    assert "Asphalt Co" not in text
    assert "Traffic Co" not in text


def test_gantt_timeline_fills_page_width_and_height():
    start = date(2026, 3, 2)
    items = [_item(i, start + timedelta(days=i)) for i in range(20)]
    avail_w, avail_h = _frame()
    tl = GanttTimeline(items, width=120)
    w, h = tl.wrap(avail_w, avail_h)
    assert abs(w - avail_w) < 1
    assert h >= avail_h - 1
    assert abs(tl.height - h) < 1
    assert abs(tl.width - w) < 1


def test_gantt_timeline_splits_tall_board_to_fill_pages():
    start = date(2026, 3, 2)
    items = [_item(i, start + timedelta(days=i)) for i in range(62)]
    avail_w, avail_h = _frame()
    tl = GanttTimeline(items, width=120)
    chunks = tl.split(avail_w, avail_h)
    assert len(chunks) >= 2
    w, h = chunks[0].wrap(avail_w, avail_h)
    assert abs(w - avail_w) < 1
    assert h >= avail_h - 1
    assert abs(chunks[0].height - h) < 1


def test_gantt_clip_text_keeps_long_roads_inside_label():
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from app.gantt_export import clip_text

    long = "54. FOOTSCRAY-CAROLINE SPRINGS RD - 55"
    fitted = clip_text(long, "Helvetica", 7, 90)
    assert stringWidth(fitted, "Helvetica", 7) <= 90.1
    assert fitted.endswith("…")
    assert "FOOTSCRAY" in fitted
    assert clip_text("S48 · Night", "Helvetica", 6, 200) == "S48 · Night"


def test_gantt_page_has_day_night_not_contractor_filters():
    assert 'id="addShiftDay"' in GANTT_HTML
    assert 'id="addShiftNight"' in GANTT_HTML
    assert "Save Gantt" in GANTT_HTML
    assert "pdf-asphalt" not in GANTT_HTML
    assert "pdf-traffic" not in GANTT_HTML
    assert "shift_type" in GANTT_JS
    assert "data-shift-day" in GANTT_JS
    assert "data-shift-night" in GANTT_JS
    assert "schedule_saved" in GANTT_JS
    assert "pdfAsphalt" not in GANTT_JS
    assert "pdfTraffic" not in GANTT_JS
