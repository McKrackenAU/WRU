"""Rules aligned to WRU Traffic TGS-MOA Tracker V6 spreadsheet."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.business_days import add_business_days
from app.calculations import (
    compute_must_have_date,
    compute_today_priority,
    must_have_status,
    moa_wait_metrics,
)
from app.settings_store import Rules


def _site(**kwargs):
    base = dict(
        workflow_steps=[],
        councils=[],
        indicative_site_start_date=None,
        moa_must_have_received_date=None,
        must_have_manual=False,
        moa_received_date=None,
        moa_submission_date=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_must_have_is_start_minus_20_business_days():
    start = date(2026, 8, 31)  # Monday
    site = _site(indicative_site_start_date=start)
    must = compute_must_have_date(site, rules=Rules())
    assert must == add_business_days(start, -20)


def test_priority_uses_must_have_not_start():
    # Must-have tomorrow → priority 1; far start date ignored
    site = _site(
        indicative_site_start_date=date(2027, 1, 1),
        moa_must_have_received_date=date.today(),
        must_have_manual=True,
    )
    assert compute_today_priority(site, rules=Rules(priority_must_have_days=14)) == 1


def test_must_have_received_label_when_moa_received():
    site = _site(moa_received_date=date(2026, 7, 1))
    st = must_have_status(site, today=date(2026, 7, 10), rules=Rules())
    assert st["band"] == "received"
    assert st["label"] == "Received"


def test_moa_wait_over_sla():
    site = _site(moa_submission_date=date(2026, 6, 1))  # Monday
    # > 20 business days later
    m = moa_wait_metrics(site, today=date(2026, 7, 6), rules=Rules(moa_wait_sla_business_days=20))
    assert m["status"] == "waiting"
    assert m["over_sla"] is True


def test_moa_wait_keeps_final_days_after_approval():
    # Submitted Mon 1 Jun; received after 10 business days (Mon 15 Jun).
    site = _site(
        moa_submission_date=date(2026, 6, 1),
        moa_received_date=date(2026, 6, 15),
    )
    m = moa_wait_metrics(site, today=date(2026, 8, 26), rules=Rules())
    assert m["status"] == "received"
    assert m["business_days_waiting"] == 10
    assert m["over_sla"] is False


def test_moa_wait_final_days_can_exceed_sla():
    site = _site(
        moa_submission_date=date(2026, 6, 1),
        moa_received_date=date(2026, 9, 14),  # long wait, then approved
    )
    m = moa_wait_metrics(site, today=date(2026, 9, 20), rules=Rules(moa_wait_sla_business_days=20))
    assert m["status"] == "received"
    assert m["business_days_waiting"] == 75
    assert m["over_sla"] is False  # SLA highlight only while still waiting
