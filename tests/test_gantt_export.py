"""Gantt PDF export pagination and calendar helpers."""

from datetime import date, timedelta

from app.gantt_export import ROWS_PER_TIMELINE_PAGE, build_gantt_pdf


def _item(i: int, start: date):
    end = start + timedelta(days=2)
    return {
        "site_road_name": f"Road {i}",
        "site_number": f"S{i:03d}",
        "shifts_count": 3,
        "subcontractor_name": "Asphalt Co",
        "traffic_contractor_name": "Traffic Co",
        "planned_start": start.isoformat(),
        "planned_end": end.isoformat(),
    }


def test_gantt_pdf_exports_large_board():
    start = date(2026, 3, 2)
    items = [_item(i, start + timedelta(days=i * 3)) for i in range(40)]
    assert len(items) > ROWS_PER_TIMELINE_PAGE
    pdf = build_gantt_pdf({"program": "Lifecycle pavements", "items": items})
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 2000
