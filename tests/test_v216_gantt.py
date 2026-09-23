"""Checkbox size, state holidays, and Sunday–Thursday night Gantt weeks."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.gantt_engine import DEFAULT_NIGHT_WEEKDAYS, recompute_board_dates, weekdays_for_shift
from app.public_holidays import holidays_for_year, holidays_between, normalize_jurisdiction

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STYLE = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
GANTT_HTML = (ROOT / "app/static/gantt.html").read_text(encoding="utf-8")
GANTT_JS = (ROOT / "app/static/js/gantt.js").read_text(encoding="utf-8")
SETTINGS_HTML = (ROOT / "app/static/settings.html").read_text(encoding="utf-8")
ACCOUNT_HTML = (ROOT / "app/static/account.html").read_text(encoding="utf-8")


def test_version_is_216():
    assert VERSION == "2.16"


def test_form_checkboxes_are_not_touch_sized():
    assert '.password-form input:not([type="checkbox"])' in STYLE
    assert '.form-grid input:not([type="checkbox"])' in STYLE
    assert ".prefs-pill input[type=\"checkbox\"]" in STYLE
    assert "width: 16px" in STYLE
    assert 'id="quickLinkPicker"' in ACCOUNT_HTML


def test_state_holidays_differ_by_region():
    vic = holidays_for_year(2026, "VIC")
    nsw = holidays_for_year(2026, "NSW")
    assert date(2026, 11, 3) in vic  # Melbourne Cup
    assert date(2026, 11, 3) not in nsw
    assert date(2026, 10, 5) in nsw  # NSW Labour Day 1st Mon Oct 2026
    assert normalize_jurisdiction("vic") == "VIC"
    span = holidays_between(date(2026, 9, 1), date(2026, 10, 1), "VIC")
    assert date(2026, 9, 25) in span  # GF Friday 2026


def test_night_weekdays_default_sun_thu():
    board = SimpleNamespace(work_weekdays=[0, 1, 2, 3, 4], night_work_weekdays=None)
    assert weekdays_for_shift(board, shift_type="night") == DEFAULT_NIGHT_WEEKDAYS
    assert weekdays_for_shift(board, shift_type="day") == [0, 1, 2, 3, 4]


def test_gantt_night_job_skips_friday_and_saturday():
    board = SimpleNamespace(
        work_weekdays=[0, 1, 2, 3, 4],
        night_work_weekdays=[6, 0, 1, 2, 3],
        holiday_region="VIC",
        rdo_dates=[],
        exclude_dates=[],
        include_dates=[],
        skip_public_holidays=True,
        skip_sunday_before_monday_ph=False,
        anchor_start=date(2026, 8, 7),  # Friday
    )
    item = SimpleNamespace(
        id=1,
        board_id=1,
        site_id=1,
        position=10,
        shifts_count=5,
        shift_type="night",
        link_mode="after_previous",
        fixed_start=None,
        subcontractor_id=None,
        traffic_contractor_id=None,
        planned_start=None,
        planned_end=None,
        rdo_dates=[],
        exclude_dates=[],
        include_dates=[],
        notes=None,
        site=None,
        subcontractor=None,
        traffic_contractor=None,
    )
    recompute_board_dates(board, [item])
    assert item.planned_start == date(2026, 8, 9)  # Sunday night
    assert item.planned_end == date(2026, 8, 14)  # Thursday night finishes Friday morning
    days = {d.weekday() for d in (date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13))}
    assert days == {6, 0, 1, 2, 3}


def test_gantt_ui_exposes_weekdays_and_region():
    assert 'id="nightWeekdays"' in GANTT_HTML
    assert 'id="dayWeekdays"' in GANTT_HTML
    assert 'id="holidayRegion"' in GANTT_HTML
    assert "night_work_weekdays" in GANTT_JS
    assert 'id="rHolidayRegion"' in SETTINGS_HTML
    assert "Sunday through Thursday" in GANTT_HTML
