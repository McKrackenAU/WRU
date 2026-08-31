"""Combined MoA applications collapse on client lists and stay separate on the register."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Site, WorkflowStep
from app.services import (
    apply_combined_application,
    group_client_list_applications,
    site_number_sort_key,
    sync_combined_application_from,
)

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
LISTS_HTML = (ROOT / "app/static/lists.html").read_text(encoding="utf-8")
EXPORT = (ROOT / "app/routers/export.py").read_text(encoding="utf-8")
SITES = (ROOT / "app/routers/sites.py").read_text(encoding="utf-8")


def test_ui_wires_combined_application_picker():
    assert 'id="combinedSitesPicker"' in INDEX
    assert "Same MoA application as" in INDEX
    assert "combined_site_ids: collectCombinedSiteIds()" in APP_JS
    assert "badge-combined" in APP_JS
    assert "show as one row" in LISTS_HTML
    assert "group_client_list_applications" in EXPORT
    assert "group_client_list_applications" in SITES


def test_site_numbers_sort_ascending():
    nums = ["S45", "S42", "S9", "S43", "S44"]
    assert sorted(nums, key=site_number_sort_key) == ["S9", "S42", "S43", "S44", "S45"]


def test_group_client_list_merges_site_numbers_and_keeps_earliest_start():
    rows = [
        {
            "id": 2,
            "road_name": "BALLARAT RD",
            "site_number": "S43",
            "moa_number": "0094708",
            "today_priority": 2,
            "indicative_site_start_date": date(2026, 10, 1),
            "combined_application_id": 1,
            "metrics": {"max_council_business_days_waiting": 3},
        },
        {
            "id": 1,
            "road_name": "BALLARAT RD",
            "site_number": "S42",
            "moa_number": "0094708",
            "today_priority": 1,
            "indicative_site_start_date": date(2026, 9, 28),
            "combined_application_id": 1,
            "metrics": {"max_council_business_days_waiting": 8},
        },
        {
            "id": 3,
            "road_name": "GEELONG RD",
            "site_number": "S44",
            "moa_number": "0094708",
            "today_priority": 2,
            "indicative_site_start_date": date(2026, 10, 5),
            "combined_application_id": 1,
            "metrics": {"max_council_business_days_waiting": 1},
        },
        {
            "id": 9,
            "road_name": "SOLO RD",
            "site_number": "S99",
            "moa_number": "111",
            "today_priority": 1,
            "indicative_site_start_date": date(2026, 8, 1),
            "combined_application_id": None,
            "metrics": {},
        },
    ]
    out = group_client_list_applications(rows)
    assert len(out) == 2
    merged = next(r for r in out if r.get("combined_application_id") == 1)
    solo = next(r for r in out if r["id"] == 9)
    assert merged["site_number"] == "S42, S43, S44"
    assert merged["road_name"] == "BALLARAT RD / GEELONG RD"
    assert merged["today_priority"] == 1
    assert merged["indicative_site_start_date"] == date(2026, 9, 28)
    assert merged["metrics"]["max_council_business_days_waiting"] == 8
    assert merged["combined_site_ids"] == [1, 2, 3]
    assert solo["site_number"] == "S99"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _site(db, name, no, **extra):
    now = datetime.now(timezone.utc)
    site = Site(
        road_name=name,
        site_number=no,
        program="Generics MTMP/ITMP",
        created_at=now,
        updated_at=now,
        custom_fields={},
        tags=[],
        **extra,
    )
    db.add(site)
    db.flush()
    return site


def test_apply_combined_groups_and_syncs_moa_not_start_date():
    db = _session()
    a = _site(
        db,
        "BALLARAT RD",
        "S42",
        moa_number="0094708",
        tgs_reference="TGS-1",
        moa_submission_date=date(2026, 8, 1),
        indicative_site_start_date=date(2026, 9, 28),
    )
    b = _site(
        db,
        "BALLARAT RD",
        "S43",
        indicative_site_start_date=date(2026, 10, 4),
    )
    a.workflow_steps.append(WorkflowStep(stage="moa_submitted", completed=True))
    a.workflow_steps.append(WorkflowStep(stage="ready_for_works", completed=False))
    b.workflow_steps.append(WorkflowStep(stage="moa_submitted", completed=False))
    b.workflow_steps.append(WorkflowStep(stage="ready_for_works", completed=True))
    db.flush()

    partners = apply_combined_application(db, a, [b.id])
    assert partners == [b.id]
    assert a.combined_application_id == a.id
    assert b.combined_application_id == a.id
    assert b.moa_number == "0094708"
    assert b.tgs_reference == "TGS-1"
    assert b.moa_submission_date == date(2026, 8, 1)
    assert b.indicative_site_start_date == date(2026, 10, 4)
    assert next(s for s in b.workflow_steps if s.stage == "moa_submitted").completed is True
    assert next(s for s in b.workflow_steps if s.stage == "ready_for_works").completed is True


def test_ungroup_clears_when_only_one_left():
    db = _session()
    a = _site(db, "A RD", "S1")
    b = _site(db, "B RD", "S2")
    apply_combined_application(db, a, [b.id])
    apply_combined_application(db, a, [])
    db.refresh(a)
    db.refresh(b)
    assert a.combined_application_id is None
    assert b.combined_application_id is None


def test_sync_skips_when_not_grouped():
    site = SimpleNamespace(id=1, combined_application_id=None)
    assert sync_combined_application_from(SimpleNamespace(query=lambda *_: None), site) == []
