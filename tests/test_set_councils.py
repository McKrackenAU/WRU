"""Council collection sync must not clear+reinsert the same names."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.models import SiteCouncil
from app.services import set_councils


def test_set_councils_updates_existing_in_place():
    existing = SiteCouncil(
        council_name="Maribyrnong",
        submitted_to_council_date=None,
        no_objection_date=None,
    )
    site = SimpleNamespace(councils=[existing])
    set_councils(
        site,
        [
            {
                "council_name": "Maribyrnong",
                "submitted_to_council_date": date(2026, 1, 15),
                "no_objection_date": None,
            }
        ],
    )
    assert len(site.councils) == 1
    assert site.councils[0] is existing
    assert site.councils[0].submitted_to_council_date == date(2026, 1, 15)


def test_set_councils_adds_and_removes():
    keep = SiteCouncil(council_name="Keep", submitted_to_council_date=None, no_objection_date=None)
    drop = SiteCouncil(council_name="Drop", submitted_to_council_date=None, no_objection_date=None)
    site = SimpleNamespace(councils=[keep, drop])
    set_councils(site, ["Keep", "New"])
    names = sorted(c.council_name for c in site.councils)
    assert names == ["Keep", "New"]
    assert keep in site.councils
    assert drop not in site.councils


def test_set_councils_none_is_noop():
    row = SiteCouncil(council_name="Only", submitted_to_council_date=None, no_objection_date=None)
    site = SimpleNamespace(councils=[row])
    set_councils(site, None)
    assert site.councils == [row]
