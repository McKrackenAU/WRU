"""Admin road lookups rename every site that uses the old name."""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.lookups import apply_lookup_update, ensure_lookup_value, sync_usage_into_lookups, usage_counts
from app.models import LookupItem, Site, SiteCouncil


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _site(db, road, site_no="S1"):
    now = datetime.now(timezone.utc)
    site = Site(
        road_name=road,
        site_number=site_no,
        created_at=now,
        updated_at=now,
        custom_fields={},
    )
    db.add(site)
    db.flush()
    return site


def test_sync_pulls_site_roads_into_admin_list():
    db = _session()
    _site(db, "WRONG RD - 1", "A")
    _site(db, "WRONG RD - 1", "B")
    _site(db, "HYDE ST - 5199", "C")
    db.commit()
    added = sync_usage_into_lookups(db, "road")
    assert added == 2
    names = {r.value for r in db.query(LookupItem).filter(LookupItem.kind == "road").all()}
    assert names == {"WRONG RD - 1", "HYDE ST - 5199"}
    counts = usage_counts(db, "road")
    assert counts["wrong rd - 1"] == 2
    assert sync_usage_into_lookups(db, "road") == 0


def test_rename_road_updates_every_matching_site():
    db = _session()
    lookup = LookupItem(kind="road", value="MC DONALD RD - 5142", position=10, active=True)
    db.add(lookup)
    a = _site(db, "MC DONALD RD - 5142", "S40")
    b = _site(db, "mc donald rd - 5142", "S41")
    other = _site(db, "PRINCES HWY WEST - 2500", "S1")
    db.commit()
    change = apply_lookup_update(db, lookup, value="MCDONALD RD - 5142", active=True)
    assert change.sites_updated == 2
    assert change.merged is False
    assert change.row.value == "MCDONALD RD - 5142"
    db.refresh(a)
    db.refresh(b)
    db.refresh(other)
    assert a.road_name == "MCDONALD RD - 5142"
    assert b.road_name == "MCDONALD RD - 5142"
    assert other.road_name == "PRINCES HWY WEST - 2500"


def test_rename_merges_into_existing_road():
    db = _session()
    keep = LookupItem(kind="road", value="PRINCES HWY WEST - 2500", position=10, active=True)
    dup = LookupItem(kind="road", value="PRINCES HWY WEST", position=20, active=True)
    db.add_all([keep, dup])
    site = _site(db, "PRINCES HWY WEST", "27D")
    db.commit()
    change = apply_lookup_update(db, dup, value="PRINCES HWY WEST - 2500", active=True)
    assert change.merged is True
    assert change.row.id == keep.id
    db.refresh(site)
    assert site.road_name == "PRINCES HWY WEST - 2500"
    leftover = db.query(LookupItem).filter(LookupItem.kind == "road").all()
    assert [r.value for r in leftover] == ["PRINCES HWY WEST - 2500"]


def test_ensure_lookup_value_restores_inactive_road():
    db = _session()
    row = LookupItem(kind="road", value="FOOTSCRAY RD - 4120", position=10, active=False)
    db.add(row)
    db.commit()
    out = ensure_lookup_value(db, "road", "FOOTSCRAY RD - 4120")
    assert out.id == row.id
    assert out.active is True
