"""Dated site notes, lifecycle shift reports, and size-banded asphalt actuals."""

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.asphalt_engine import pick_area_band_rate
from app.database import Base
from app.models import (
    ActualSpend,
    AsphaltRate,
    AsphaltSubcontractor,
    LabourRate,
    ShiftReport,
    Site,
)
from app.shift_costs import hours_between, post_shift_spend

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
SHIFTS_HTML = (ROOT / "app/static/shifts.html").read_text(encoding="utf-8")
SHIFTS_JS = (ROOT / "app/static/js/shifts.js").read_text(encoding="utf-8")
RATES_HTML = (ROOT / "app/static/asphalt-rates.html").read_text(encoding="utf-8")
RATES_JS = (ROOT / "app/static/js/asphalt-rates.js").read_text(encoding="utf-8")
ENGINE = (ROOT / "app/asphalt_engine.py").read_text(encoding="utf-8")


def _rate(**kwargs):
    base = {
        "id": 1,
        "name": "14HP",
        "unit": "m2",
        "active": True,
        "day_rate": 10,
        "night_rate": 10,
        "area_min_m2": None,
        "area_max_m2": None,
        "thickness_mm": None,
    }
    base.update(kwargs)
    return base


def test_version_is_219():
    assert VERSION == "2.21"


def test_note_log_is_dated_and_shared_with_activity():
    assert 'id="noteDraft"' in INDEX
    assert 'id="btnSaveNote"' in INDEX
    assert 'id="noteLog"' in INDEX
    assert "event_type: \"note\"" in APP_JS
    assert "isNoteEvent" in APP_JS
    assert "Save the site first, then add a dated note." in APP_JS


def test_shift_form_picks_road_then_site_and_draws_polygons():
    assert 'id="shiftRoad"' in SHIFTS_HTML
    assert 'id="shiftSite"' in SHIFTS_HTML
    assert 'id="shiftMap"' in SHIFTS_HTML
    assert 'id="dPostSpend"' in SHIFTS_HTML
    assert "Select a road first" in SHIFTS_JS
    assert "drawLayer.addLayer" in SHIFTS_JS
    assert "actual-spend" in SHIFTS_JS
    assert "site_area_m2" in SHIFTS_JS
    assert 'id="rateAreaMin"' in RATES_HTML
    assert 'id="rateThickness"' in RATES_HTML
    assert "area_min_m2" in RATES_JS
    assert "pick_area_band_rate" in ENGINE


def test_area_band_uses_the_whole_site_not_the_shift_quantity():
    small = _rate(id=1, name="14HP 50mm", day_rate=20, area_min_m2=0, area_max_m2=5000, thickness_mm=50)
    large = _rate(id=2, name="14HP 50mm", day_rate=12, area_min_m2=5000, area_max_m2=10000, thickness_mm=50)
    other = _rate(id=3, name="10mm", day_rate=9, area_min_m2=5000, area_max_m2=10000, thickness_mm=50)
    open_rate = _rate(id=4, name="14HP 50mm", day_rate=6)
    chosen = pick_area_band_rate(
        [small, large, other, open_rate],
        mix="14HP",
        unit="m2",
        thickness_mm=50,
        site_area_m2=6000,
    )
    assert chosen["id"] == 2
    partial_site = pick_area_band_rate(
        [small, large, open_rate],
        mix="14HP",
        unit="m2",
        thickness_mm=50,
        site_area_m2=2000,
    )
    assert partial_site["id"] == 1
    tonne = pick_area_band_rate(
        [large, _rate(id=5, name="14HP", unit="tonne", day_rate=180)],
        mix="14HP",
        unit="tonne",
        thickness_mm=50,
        site_area_m2=6000,
    )
    assert tonne["unit"] == "tonne"
    thin = pick_area_band_rate(
        [large, _rate(id=6, name="14HP 40mm", day_rate=15, area_min_m2=5000, area_max_m2=10000, thickness_mm=40)],
        mix="14HP",
        unit="m2",
        thickness_mm=40,
        site_area_m2=6000,
    )
    assert thin["thickness_mm"] == 40


def test_hours_between_rolls_overnight_shifts():
    assert hours_between("2026-09-22T19:00", "2026-09-23T05:00") == 10
    assert hours_between("2026-09-23T19:00", "2026-09-23T05:00") == 10
    assert hours_between("", "2026-09-23T05:00") is None
    assert hours_between("not-a-date", "also-bad") is None


def test_post_shift_spend_prices_m2_from_site_band_and_tonnes_when_present():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    site = Site(road_name="HEATHS RD", site_number="5443")
    db.add(site)
    db.flush()
    sub = AsphaltSubcontractor(name="Boral")
    db.add(sub)
    db.flush()
    db.add_all(
        [
            AsphaltRate(
                subcontractor_id=sub.id,
                name="14HP 50mm",
                unit="m2",
                rate_type="unit",
                day_rate=20,
                night_rate=20,
                area_min_m2=0,
                area_max_m2=5000,
                thickness_mm=50,
            ),
            AsphaltRate(
                subcontractor_id=sub.id,
                name="14HP 50mm",
                unit="m2",
                rate_type="unit",
                day_rate=12,
                night_rate=12,
                area_min_m2=5000,
                area_max_m2=10000,
                thickness_mm=50,
            ),
            AsphaltRate(
                subcontractor_id=sub.id,
                name="14HP",
                unit="tonne",
                rate_type="unit",
                day_rate=180,
                night_rate=180,
            ),
            LabourRate(
                name="2 TC + ute",
                rate_kind="crew_pack",
                pack_people=2,
                includes_vehicle=True,
                day_ordinary=100,
                day_overtime=150,
                night_ordinary=120,
                night_overtime=180,
            ),
        ]
    )
    report = ShiftReport(
        site_id=site.id,
        work_date=date(2026, 9, 13),
        shift_type="night",
        details={
            "traffic_crew_start": "2026-09-13T19:00",
            "traffic_crew_end": "2026-09-14T05:00",
            "total_tc": 2,
            "vehicles": 1,
            "asphalt_type": "14HP",
            "thickness_mm": 50,
            "shift_area_m2": 2000,
            "site_area_m2": 6000,
            "paving_contractor": "Boral",
        },
        polygons=[{"type": "Feature"}, {"type": "Feature"}],
    )
    db.add(report)
    db.commit()

    result = post_shift_spend(db, report, created_by="Will")
    assert result["posted"]["asphalt"]["amount"] == 24000
    assert result["posted"]["asphalt"]["unit"] == "m2"
    assert result["posted"]["asphalt"]["quantity"] == 2000
    assert result["posted"]["traffic"]["hours"] == 10
    assert result["posted"]["traffic"]["amount"] > 0

    report.details = {**report.details, "tonnage": 384, "shift_area_m2": 2000}
    again = post_shift_spend(db, report, created_by="Will")
    assert again["posted"]["asphalt"]["unit"] == "tonne"
    assert again["posted"]["asphalt"]["amount"] == 384 * 180
    rows = db.query(ActualSpend).filter(ActualSpend.site_id == site.id).all()
    assert {row.kind for row in rows} == {"traffic", "asphalt"}
    assert all(row.inputs.get("shift_id") == report.id for row in rows)
    db.close()
