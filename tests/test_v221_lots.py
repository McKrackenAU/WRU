"""Lot numbers, the QA register, and the site works map."""

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.lot_map import _expand, render_lot_map
from app.lot_numbers import build_lot_number, compact_fmrp, road_number_from_name, supervisor_initials
from app.lot_register import sync_lot
from app.models import LotRegister, ShiftReport, Site
from app.shift_export import report_reference

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
SHIFTS_JS = (ROOT / "app/static/js/shifts.js").read_text(encoding="utf-8")
LOTS_HTML = (ROOT / "app/static/lots.html").read_text(encoding="utf-8")
LOTS_JS = (ROOT / "app/static/js/lots.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")


def test_version_is_221():
    assert VERSION == "2.21"


def test_lot_number_order_matches_the_old_filename():
    assert compact_fmrp("FMRP 2025/26") == "2526"
    assert compact_fmrp("2025/26") == "2526"
    assert road_number_from_name("DYNON RD - 5035") == "5035"
    assert road_number_from_name("HEATHS RD - 5443") == "5443"
    assert supervisor_initials("William McClure") == "WM"
    lot = build_lot_number(
        work_date="2026-02-25",
        road_number="5443",
        fmrp_year="FMRP 2025/26",
        site_number="030",
        work_kind="hma",
        mix="14HP",
        supervisor="William McClure",
    )
    assert lot == "20260225-5443-2526-030-HMA-14HP-WM"
    profiling = build_lot_number(
        work_date="2026-02-25",
        road_number="5443",
        fmrp_year="FMRP 2025/26",
        site_number="030",
        work_kind="pro",
        mix="14HP",
        supervisor="William McClure",
    )
    assert profiling == "20260225-5443-2526-030-PRO-WM"
    assert "14HP" not in profiling


def test_profile_report_reference_drops_the_mix():
    report = {
        "work_date": "2026-02-25",
        "road_name": "HEATHS RD - 5443",
        "site_number": "030",
        "crew": "William McClure",
        "details": {"fmrp_year": "FMRP 2025/26", "work_kind": "profiling", "asphalt_type": "14HP"},
    }
    site = {"road_name": "HEATHS RD - 5443", "site_number": "030"}
    assert report_reference(report, site) == "20260225-5443-2526-030-PRO-WM"


def test_lot_map_keeps_context_around_the_polygon():
    rings = [[(144.95, -37.80), (144.955, -37.80), (144.955, -37.802), (144.95, -37.802)]]
    south, north, west, east = _expand(rings)
    assert south < -37.802
    assert north > -37.80
    assert west < 144.95
    assert east > 144.955
    assert render_lot_map([{"type": "Polygon", "coordinates": [rings[0]]}], "LOT") is None


def test_sync_lot_registers_one_row_per_shift_and_suffixes_clashes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    site = Site(road_name="HEATHS RD - 5443", site_number="030")
    db.add(site)
    db.flush()
    details = {
        "fmrp_year": "FMRP 2025/26",
        "road_number": "5443",
        "work_kind": "hma",
        "asphalt_type": "14HP",
        "supervisor": "William McClure",
    }
    first = ShiftReport(site_id=site.id, work_date=date(2026, 2, 25), shift_type="night", details=dict(details))
    second = ShiftReport(site_id=site.id, work_date=date(2026, 2, 25), shift_type="night", details=dict(details))
    db.add(first)
    db.flush()
    sync_lot(db, first)
    db.add(second)
    db.flush()
    sync_lot(db, second)
    db.commit()
    rows = db.query(LotRegister).order_by(LotRegister.id).all()
    assert [row.lot_number for row in rows] == [
        "20260225-5443-2526-030-HMA-14HP-WM",
        "20260225-5443-2526-030-HMA-14HP-WM-2",
    ]
    assert rows[0].qa_status == "pending"
    assert rows[0].mix == "14HP"
    assert first.details["lot_number"] == rows[0].lot_number
    db.close()


def test_works_map_and_lot_register_are_in_the_ui():
    assert 'data-tab="works"' in INDEX
    assert 'id="siteWorksMap"' in INDEX
    assert 'id="worksMixFilters"' in INDEX
    assert "refreshSiteWorks" in APP_JS
    assert "data-mix" in APP_JS
    assert "nearmap.com/tiles" in SHIFTS_JS
    assert 'href: "/lots"' in COMMON
    assert 'id="lotsTable"' in LOTS_HTML
    assert "qa_status" in LOTS_JS
