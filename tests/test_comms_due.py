"""Comms due dates, calendar colours, and field-removal wiring."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.business_days import add_business_days
from app.comms_due import (
    STATUS_COMPLETED,
    STATUS_OPEN,
    STATUS_OVERDUE,
    build_calendar_item,
    calendar_color,
    compute_auto_due,
    item_status,
    resolve_due_date,
    should_notify_status,
)

ROOT = Path(__file__).resolve().parent.parent
COMMS_JS = (ROOT / "app/static/js/comms.js").read_text(encoding="utf-8")
COMMS_HTML = (ROOT / "app/static/comms.html").read_text(encoding="utf-8")
CAL_JS = (ROOT / "app/static/js/calendar.js").read_text(encoding="utf-8")
CAL_HTML = (ROOT / "app/static/calendar.html").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
NOTIFY = (ROOT / "app/notify.py").read_text(encoding="utf-8")


def test_auto_due_is_business_days_before_start():
    start = date(2026, 9, 14)
    field = SimpleNamespace(offset_days=5, track_due=True, field_key="letter_drop", name="Letter drop")
    site = SimpleNamespace(indicative_site_start_date=start)
    due = compute_auto_due(field, site)
    assert due == add_business_days(start, -5)
    assert due < start


def test_manual_due_used_when_auto_off():
    field = SimpleNamespace(offset_days=10, track_due=True, field_key="letter_drop", name="Letter drop")
    due = resolve_due_date(
        field,
        {"letter_drop__due": "2026-09-01", "letter_drop__due_auto": "0"},
        SimpleNamespace(indicative_site_start_date=date(2026, 9, 20)),
    )
    assert due == date(2026, 9, 1)


def test_traffic_light_and_notify_window():
    today = date(2026, 9, 1)
    assert item_status(True, date(2026, 8, 1), today) == STATUS_COMPLETED
    assert calendar_color(STATUS_COMPLETED) == "green"
    assert item_status(False, date(2026, 8, 30), today) == STATUS_OVERDUE
    assert calendar_color(STATUS_OVERDUE) == "red"
    assert item_status(False, date(2026, 9, 10), today) == STATUS_OPEN
    assert calendar_color(STATUS_OPEN) == "yellow"
    assert should_notify_status(STATUS_OVERDUE, date(2026, 8, 30), today)
    assert should_notify_status(STATUS_OPEN, today + timedelta(days=2), today)
    assert not should_notify_status(STATUS_OPEN, today + timedelta(days=10), today)


def test_calendar_item_skips_undated_open_work():
    field = SimpleNamespace(track_due=True, offset_days=None, field_key="letter_drop", name="Letter drop", id=1)
    row = SimpleNamespace(id=9, sheet_id=2, site_id=3, form_values={}, section="Works")
    assert build_calendar_item(field, row, None) is None


def test_field_remove_and_due_ui_wired():
    assert "data-del-form-field" in COMMS_JS
    assert "Remove field" in COMMS_JS
    assert "formFieldTrackDue" in COMMS_HTML
    assert "formFieldOffsetDays" in COMMS_HTML
    assert "data-form-due" in COMMS_JS
    assert "data-form-done" in COMMS_JS
    assert "track_due" in COMMS_JS
    assert 'href: "/calendar"' in COMMON
    assert "calendar_page" in MAIN
    assert "/api/calendar/comms" in CAL_JS
    assert 'id="calGrid"' in CAL_HTML
    assert "TRIGGER_COMMS_DUE" in NOTIFY
    assert "dispatch_comms_due_notifications" in NOTIFY
